"""User-scoped durable analysis manifests, artifacts, and worker leases.

Cloud Run's disk is a working cache. Firestore keeps the source snapshot, model
batch caches, agent bundle and presentation data so a replacement server can
open completed work or resume an interrupted analysis.
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path

from analysis_pipeline import AnalysisError, AnalysisLibrary, now, run_pipeline
from filter_comments import digest, write_json


class LeaseLost(RuntimeError):
    pass


class AnalysisArtifacts:
    def __init__(self, root, store):
        self.root, self.store = Path(root), store
        self.lock = threading.RLock()
        self.hashes, self.versions = {}, {}
        self.restored = False

    def restore(self):
        with self.lock:
            if self.restored:
                return
            for file_id in self.store.list_ids('analysis_files'):
                value = self.store.load('analysis_files/'+file_id)
                if not value:
                    continue
                relative = value['path']
                path = (self.root/relative).resolve()
                if not path.is_relative_to(self.root.resolve()) or not relative.endswith('.json'):
                    raise ValueError('Invalid stored artifact path.')
                # Write atomically, including hidden .cache files.
                write_json(path, json.loads(value['content']))
                self.hashes[relative] = digest(value['content'])
                self.versions[relative] = digest(value)
            self.restored = True

    def sync(self):
        with self.lock:
            for path in self.root.rglob('*.json'):
                relative = path.relative_to(self.root).as_posix()
                if relative == 'analysis.json' or '.rejected' in path.parts:
                    continue
                content = path.read_text(encoding='utf-8')
                fingerprint = digest(content)
                if self.hashes.get(relative) == fingerprint:
                    continue
                # A stage file is only durable once it is valid JSON. Writers
                # replace completed files atomically; .tmp files are excluded.
                json.loads(content)
                key = 'analysis_files/'+digest(relative)
                previous = self.versions.get(relative)
                if relative not in self.versions:
                    existing = self.store.load(key)
                    previous = digest(existing) if existing is not None else None
                value = {'path': relative, 'content': content, 'updated_at': now()}
                self.store.save(key, value, previous)
                self.hashes[relative], self.versions[relative] = fingerprint, digest(value)


class CloudAnalysisLibrary(AnalysisLibrary):
    LEASE_SECONDS = 180

    def __init__(self, root, example_data, settings, store, *, executor=None, runner=run_pipeline):
        self.store, self.worker_id = store, uuid.uuid4().hex
        self.artifacts, self.live = {}, set()
        self.queue_watchers, self.stopping = set(), threading.Event()
        self.pipeline = runner
        super().__init__(root, example_data, settings, runner=self.durable_run, executor=executor, load_local=False)
        self.refresh()

    def files(self, analysis_id):
        with self.lock:
            if analysis_id not in self.artifacts:
                self.artifacts[analysis_id] = AnalysisArtifacts(self.root/analysis_id, self.store.for_analysis(analysis_id))
            return self.artifacts[analysis_id]

    def refresh(self):
        with self.lock:
            for analysis_id in self.store.list_ids('analyses'):
                if re.fullmatch('[a-f0-9]{32}', analysis_id):
                    self.get(analysis_id)

    def listing(self):
        self.refresh()
        return {**super().listing(), 'storage': 'account'}

    def get(self, analysis_id):
        if analysis_id == 'example':
            return super().get(analysis_id)
        if not re.fullmatch('[a-f0-9]{32}', analysis_id):
            raise FileNotFoundError('Analysis not found.')
        with self.lock:
            record = self.store.load('analyses/'+analysis_id)
            if record is None:
                raise FileNotFoundError('Analysis not found.')
            if record['status'] in ('queued', 'running') and record.get('lease_until', 0) < time.time():
                changed = {**record, 'status': 'interrupted', 'updated_at': now(),
                           'detail': 'Analysis was interrupted. Resume to continue from saved results.'}
                try:
                    self.store.save('analyses/'+analysis_id, changed, digest(record))
                    record = changed
                except ValueError:
                    record = self.store.load('analyses/'+analysis_id)
            self.records[analysis_id] = record
            return json.loads(json.dumps(record))

    def update(self, analysis_id, **changes):
        with self.lock:
            previous = self.store.load('analyses/'+analysis_id)
            if previous and previous.get('lease_owner') not in (None, self.worker_id) and previous.get('lease_until', 0) > time.time():
                raise LeaseLost('Another server owns this analysis.')
            record = {**(previous or self.records[analysis_id]), **changes, 'updated_at': now()}
            if record['status'] in ('queued', 'running'):
                record.update(lease_owner=self.worker_id, lease_until=time.time()+self.LEASE_SECONDS)
            else:
                record.update(lease_owner=None, lease_until=0)
            self.store.save('analyses/'+analysis_id, record, digest(previous) if previous is not None else None)
            self.records[analysis_id] = record
            write_json(self.root/analysis_id/'analysis.json', record)
            if record['status'] == 'queued' and analysis_id not in self.queue_watchers:
                self.queue_watchers.add(analysis_id)
                threading.Thread(target=self.keep_queued, args=(analysis_id,), daemon=True).start()

    def keep_queued(self, analysis_id):
        try:
            while not self.stopping.wait(30):
                try:
                    with self.lock:
                        record = self.store.load('analyses/'+analysis_id)
                        if not record or record['status'] != 'queued' or record.get('lease_owner') != self.worker_id:
                            return
                        self.update(analysis_id)
                except Exception as exc:
                    print(f'Analysis queue heartbeat retry: {type(exc).__name__}', flush=True)
        finally:
            with self.lock:
                self.queue_watchers.discard(analysis_id)

    def start(self, body):
        with self.lock:
            self.refresh()
            return super().start(body)

    def retry(self, analysis_id):
        with self.lock:
            self.get(analysis_id)
            return super().retry(analysis_id)

    def run(self, analysis_id):
        try:
            super().run(analysis_id)
        except LeaseLost:
            pass

    def durable_run(self, root, record, settings, update):
        analysis_id = record['analysis_id']
        files = self.files(analysis_id)
        stop = threading.Event()
        with self.lock:
            self.live.add(analysis_id)

        def heartbeat():
            while not stop.wait(15):
                try:
                    self.update(analysis_id)
                    files.sync()
                except LeaseLost:
                    return
                except Exception as exc:
                    # Never log credentials or provider data. A temporary storage
                    # outage is retried; final completion still requires a save.
                    print(f'Analysis checkpoint retry: {type(exc).__name__}', flush=True)

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            files.restore()
            def checkpoint(**changes):
                self.update(analysis_id, **changes)
                if 'stage' in changes:
                    files.sync()
            self.pipeline(root, record, settings, checkpoint)
        finally:
            stop.set()
            thread.join(timeout=30)
            try:
                self.update(analysis_id)
                files.sync()
            finally:
                with self.lock:
                    self.live.discard(analysis_id)

    def application(self, analysis_id, factory):
        with self.lock:
            if analysis_id != 'example':
                record = self.get(analysis_id)
                if record['status'] != 'ready':
                    raise AnalysisError('Wait for this analysis to finish before opening it.')
                self.files(analysis_id).restore()
            return super().application(analysis_id, factory)

    def close(self):
        self.stopping.set()
        super().close()
