import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from analysis_pipeline import AnalysisError
from cloud_analyses import AnalysisArtifacts, CloudAnalysisLibrary, LeaseLost
from filter_comments import digest, write_json
from test_analysis_pipeline import PipelineClient
from test_firebase_backend import MemoryStore


class NamespacedStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.children = {}

    def for_analysis(self, aid):
        with self.lock:
            return self.children.setdefault(aid, NamespacedStore())


class CloudAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = NamespacedStore()
        self.example = self.root/'example'
        write_json(self.example/'04_web/catalog.json', {'video': {'video_id': 'BAHKmi4F1L8', 'title': 'Example'},
                                                       'agents': [{}], 'counts': {'collected': 10}})
        self.release, self.entered = threading.Event(), threading.Event()
        self.failure = None
        def runner(root, record, settings, update):
            self.entered.set()
            write_json(root/'00_source/comments.json', {'comments': [{'text': 'Original source'}]})
            write_json(root/'01_filter/.cache/accepted.json', {'data': 'validated batch'})
            update(stage='filter', collected_count=10)
            self.release.wait(3)
            if self.failure:
                raise self.failure
            write_json(root/'03_agents/agents.json', {'agents': ['supported agent']})
            update(stage='presentation', agent_count=1)
        self.runner = runner
        self.libraries = []
        self.patch = patch('analysis_pipeline.create_client', return_value=PipelineClient())
        self.patch.start()

    def tearDown(self):
        self.release.set()
        for library in self.libraries:
            library.close()
            library.executor.shutdown(wait=True)
        self.patch.stop()
        self.tmp.cleanup()

    def library(self, name='runtime', store=None, runner=None):
        library = CloudAnalysisLibrary(self.root/name, self.example, {'YOUTUBE_API_KEY': 'test'},
                                       store or self.store, runner=runner or self.runner)
        self.libraries.append(library)
        return library

    def wait(self, library, aid):
        deadline = time.monotonic()+5
        while library.get(aid)['status'] in ('queued', 'running'):
            if time.monotonic() > deadline:
                self.fail('Worker did not finish.')
            time.sleep(.01)
        return library.get(aid)

    def test_completed_sources_caches_and_agents_survive_ephemeral_disk_loss(self):
        library = self.library()
        self.release.set()
        record = library.start({'url': 'BAHKmi4F1L8'})
        self.assertEqual(self.wait(library, record['analysis_id'])['status'], 'ready')
        library.executor.shutdown(wait=True)
        shutil.rmtree(library.root)
        restored = self.library()
        factory = Mock(side_effect=lambda path: SimpleNamespace(root=path, executor=Mock(), titles=Mock()))
        target = restored.application(record['analysis_id'], factory).root
        self.assertEqual(json.loads((target/'00_source/comments.json').read_text())['comments'][0]['text'], 'Original source')
        self.assertEqual(json.loads((target/'01_filter/.cache/accepted.json').read_text())['data'], 'validated batch')
        self.assertEqual(json.loads((target/'03_agents/agents.json').read_text())['agents'], ['supported agent'])
        self.assertEqual(restored.listing()['storage'], 'account')

    def test_other_user_cannot_read_or_open_the_analysis(self):
        library = self.library()
        self.release.set()
        record = library.start({'url': 'BAHKmi4F1L8'})
        self.wait(library, record['analysis_id'])
        other = self.library('other-user', store=NamespacedStore())
        self.assertEqual(len(other.listing()['analyses']), 1)
        with self.assertRaises(FileNotFoundError):
            other.get(record['analysis_id'])
        with self.assertRaises(FileNotFoundError):
            other.application(record['analysis_id'], Mock())
        self.store.for_analysis(record['analysis_id']).save('profile/state', {'initial_opinion': 'Private view'}, None)
        self.assertIsNone(other.store.for_analysis(record['analysis_id']).load('profile/state'))

    def test_another_server_observes_running_job_without_interrupting_or_duplicating_it(self):
        library = self.library()
        record = library.start({'url': 'BAHKmi4F1L8'})
        self.assertTrue(self.entered.wait(2))
        other = self.library('another-server')
        self.assertEqual(other.get(record['analysis_id'])['status'], 'running')
        self.assertEqual(other.start({'url': 'BAHKmi4F1L8'})['analysis_id'], record['analysis_id'])
        with self.assertRaises(LeaseLost):
            other.update(record['analysis_id'], status='running')
        self.release.set()
        self.assertEqual(self.wait(library, record['analysis_id'])['status'], 'ready')
        self.assertEqual(other.get(record['analysis_id'])['status'], 'ready')

    def test_failed_job_keeps_partial_batches_and_resumes_after_restart(self):
        library = self.library()
        self.failure = RuntimeError('sensitive provider data')
        self.release.set()
        record = library.start({'url': 'BAHKmi4F1L8'})
        failed = self.wait(library, record['analysis_id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertNotIn('sensitive', json.dumps(failed))
        library.executor.shutdown(wait=True)
        shutil.rmtree(library.root)
        self.failure = None
        def resumed(root, record, settings, update):
            self.assertTrue((root/'01_filter/.cache/accepted.json').exists())
            write_json(root/'03_agents/agents.json', {'agents': ['resumed']})
        restored = self.library(runner=resumed)
        restored.retry(record['analysis_id'])
        self.assertEqual(self.wait(restored, record['analysis_id'])['status'], 'ready')

    def test_expired_lease_becomes_resumable(self):
        library = self.library()
        self.release.set()
        record = library.start({'url': 'BAHKmi4F1L8'})
        self.wait(library, record['analysis_id'])
        key = 'analyses/'+record['analysis_id']
        previous = self.store.load(key)
        self.store.save(key, {**previous, 'status': 'running', 'lease_owner': 'dead-server', 'lease_until': 1}, digest(previous))
        restored = self.library('replacement')
        self.assertEqual(restored.get(record['analysis_id'])['status'], 'interrupted')
        restored.retry(record['analysis_id'])
        self.assertEqual(self.wait(restored, record['analysis_id'])['status'], 'ready')

    def test_artifacts_reject_path_traversal(self):
        value = {'path': '../escape.json', 'content': '{}'}
        self.store.save('analysis_files/x', value, None)
        with self.assertRaises(ValueError):
            AnalysisArtifacts(self.root/'safe', self.store).restore()
