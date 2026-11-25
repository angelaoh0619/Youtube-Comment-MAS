import copy
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from analysis_pipeline import AnalysisError, AnalysisLibrary, run_pipeline
from collect_comments import YouTubeError, collect_video, parse_video_id
from filter_comments import write_json
from llm_client import ModelError
from test_filter_comments import decision
from test_group_comments import FakeClient, comment
from web_data import WebData


class PipelineClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.fail_presentation = False

    def structured(self, system, payload, schema, name):
        if name in ('discover', 'assign', 'summarize'):
            return super().structured(system, payload, schema, name)
        self.requests += 1
        self.calls.append((name, copy.deepcopy(payload)))
        if name == 'comment_languages':
            data = {'languages': ['ko', 'en']}
        elif name == 'comment_filter':
            data = {'decisions': [decision(c['comment_id']) for c in payload['comments']]}
        elif name == 'english_perspectives':
            if self.fail_presentation:
                raise ModelError('private-provider-payload')
            data = {'agents': [{'agent_id': p['agent_id'], 'emoji': '🧭' if p['agent_id']=='g1' else '🌱', 'title': 'Perspective '+p['agent_id'],
                                'subtitle': 'A comment perspective', 'stance': 'A supported stance.',
                                'reasoning': 'Reasons from source comments.'} for p in payload['agents']]}
        elif name == 'web_translation':
            data = {'translations': [{'id': x['id'], 'text': 'English source translation.'} for x in payload['items']]}
        else:
            raise AssertionError(name)
        return {'data': data, 'model': self.model}


class CollectorTests(unittest.TestCase):
    def test_video_links_are_normalized_and_foreign_hosts_rejected(self):
        for value in ('BAHKmi4F1L8', 'https://www.youtube.com/watch?v=BAHKmi4F1L8&t=42',
                      'youtu.be/BAHKmi4F1L8', 'https://youtube.com/shorts/BAHKmi4F1L8',
                      'https://www.youtube.com/live/BAHKmi4F1L8?si=123'):
            self.assertEqual(parse_video_id(value), 'BAHKmi4F1L8')
        for value in ('https://evil.example/watch?v=BAHKmi4F1L8', 'https://evilyoutu.be/BAHKmi4F1L8',
                      'file:///watch?v=BAHKmi4F1L8', 'https://youtube.com/playlist?list=123', 'not a link'):
            with self.assertRaises(ValueError):
                parse_video_id(value)

    def test_limit_includes_replies_and_preserves_parent_context(self):
        def item(cid):
            return {'id': cid, 'snippet': {'textDisplay': 'A real view', 'publishedAt': '2026-01-01'}}
        class API:
            requests = 0
            reply_calls = 0
            def get(self, endpoint, **params):
                self.requests += 1
                if endpoint == 'videos':
                    return {'items': [{'snippet': {'title': 'A video'}, 'statistics': {'commentCount': '10000'}}]}
                if endpoint == 'commentThreads':
                    return {'items': [{'snippet': {'topLevelComment': item('parent'), 'totalReplyCount': 10000}}], 'nextPageToken': 'next'}
                self.reply_calls += 1
                return {'items': [item('r'+str(i)) for i in range(100)], 'nextPageToken': 'more'}
        api, progress = API(), []
        result = collect_video(api, 'BAHKmi4F1L8', max_comments=5, progress=progress.append)
        self.assertEqual(len(result['comments']), 5)
        self.assertEqual(result['comments'][0]['comment_id'], 'parent')
        self.assertTrue(all(c['parent_id'] == 'parent' for c in result['comments'][1:]))
        self.assertEqual(api.reply_calls, 1)
        self.assertEqual(progress[-1], 5)
        self.assertTrue(result['meta']['limit_reached'])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.client = PipelineClient()
        self.source = {'meta': {'video_id': 'BAHKmi4F1L8', 'title': 'A new topic', 'limit_reached': False},
                       'comments': [comment('parent', '찬성합니다'), comment('reply', '반대합니다', 'parent')]}
        self.record = {'video_id': 'BAHKmi4F1L8', 'max_comments': 200, 'with_replies': True, 'topic': ''}
        self.settings = {'YOUTUBE_API_KEY': 'test'}
        self.progress = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_pipeline(self):
        with patch('analysis_pipeline.create_client', return_value=self.client), \
             patch('analysis_pipeline.YouTubeAPI') as api, \
             patch('analysis_pipeline.collect_video', return_value=copy.deepcopy(self.source)) as collector:
            api.return_value.get.return_value = {'items': [{'snippet': {'title': 'A new topic'}}]}
            run_pipeline(self.root, self.record, self.settings, lambda **change: self.progress.append(change))
        return collector

    def test_complete_pipeline_keeps_evidence_and_retry_reuses_completed_steps(self):
        collector = self.run_pipeline()
        collector.assert_called_once()
        data = WebData(self.root, self.client)
        self.assertEqual(len(data.catalog()['agents']), 2)
        self.assertEqual({a['emoji'] for a in data.catalog()['agents']}, {'🧭', '🌱'})
        self.assertEqual(data.catalog()['video']['source_languages'], ['ko', 'en'])
        self.assertEqual({c['comment_id'] for p in data.bundle['agents'] for c in p['comments']}, {'parent', 'reply'})
        calls = self.client.requests
        self.run_pipeline().assert_not_called()
        self.assertEqual(self.client.requests, calls)
        self.assertEqual([p['stage'] for p in self.progress if 'stage' in p][-4:], ['filter', 'group', 'agents', 'presentation'])

    def test_failure_during_presentation_resumes_without_refiltering(self):
        self.client.fail_presentation = True
        with self.assertRaises(ModelError):
            self.run_pipeline()
        previous = [n for n, _ in self.client.calls].count('comment_filter')
        self.client.fail_presentation = False
        self.run_pipeline().assert_not_called()
        self.assertEqual([n for n, _ in self.client.calls].count('comment_filter'), previous)
        self.assertEqual(len(WebData(self.root, self.client).catalog()['agents']), 2)

    def test_retrieval_uses_this_videos_languages(self):
        self.run_pipeline()
        data = WebData(self.root, self.client)
        data.filter_meta['source_meta']['source_languages'] = ['ja', 'en']
        data.translator.translate = Mock(return_value=['検索語'])
        self.assertEqual(data.retrieval_query('My question', 'en'), 'My question\n検索語')
        data.translator.translate.assert_called_once_with(['My question'], 'ja')

    def test_http_requests_keep_rooms_and_jobs_inside_the_selected_analysis(self):
        from web_server import Application, Handler
        self.run_pipeline()
        library = AnalysisLibrary(self.root/'runs', self.root, {})
        for aid in ('a'*32, 'b'*32):
            target = library.root/aid
            for folder in ('01_filter', '02_group', '03_agents', '04_web'):
                shutil.copytree(self.root/folder, target/folder)
            library.records[aid] = {'analysis_id': aid, 'status': 'ready'}
        app = Application(self.root, self.client)
        library.apps['example'] = app
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app, server.library, server.example_data = app, library, self.root
        server.allowed_origins = set()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, scope, body=None):
            headers = {'X-Analysis-ID': scope}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            req = Request(f'http://127.0.0.1:{server.server_port}/api'+path,
                          data=json.dumps(body).encode() if body is not None else None, headers=headers)
            try:
                with urlopen(req, timeout=5) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                with exc:
                    return exc.code, json.load(exc)
        try:
            status, room = request('/rooms', 'a'*32, {'participants': ['g1'], 'initial_opinion': 'My own view'})
            self.assertEqual(status, 201)
            self.assertEqual(request('/rooms/'+room['room_id'], 'a'*32)[0], 200)
            self.assertEqual(request('/rooms/'+room['room_id'], 'b'*32)[0], 404)
            self.assertEqual(request('/bootstrap', 'b'*32)[1]['rooms'], [])
            first = library.apps['a'*32]
            first.jobs['c'*32] = {'job_id': 'c'*32, 'status': 'completed', 'result': 'private result'}
            self.assertEqual(request('/jobs/'+'c'*32, 'a'*32)[0], 200)
            self.assertEqual(request('/jobs/'+'c'*32, 'b'*32)[0], 404)
            self.assertEqual(request('/bootstrap', '../.env')[0], 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            library.close()

    def test_authenticated_cloud_routes_enable_analysis_and_isolate_video_profiles(self):
        from web_server import Accounts, Handler
        from test_firebase_backend import FakeBackend
        from test_cloud_analyses import NamespacedStore
        self.run_pipeline()
        backend = FakeBackend()
        backend.stores = {'alice': NamespacedStore(), 'bob': NamespacedStore()}
        accounts = Accounts(self.root, self.client, backend, self.root/'cloud-runtime', {'YOUTUBE_API_KEY': 'test'})
        library = accounts.library_for_user('alice')
        def pipeline(target, record, settings, update):
            for folder in ('01_filter', '02_group', '03_agents', '04_web'):
                shutil.copytree(self.root/folder, target/folder, dirs_exist_ok=True)
            update(stage='presentation', agent_count=2, collected_count=2)
        library.pipeline = pipeline
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app, server.library, server.example_data = accounts, None, self.root
        server.allowed_origins = set()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, user='alice', scope='example', body=None, method=None):
            headers = {'Authorization': 'Bearer '+user, 'X-Analysis-ID': scope}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            req = Request(f'http://127.0.0.1:{server.server_port}/api'+path,
                          data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
            try:
                with urlopen(req, timeout=5) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                with exc:
                    return exc.code, json.load(exc)
        try:
            self.assertTrue(request('/analyses')[1]['can_analyze'])
            with patch('analysis_pipeline.create_client', return_value=self.client):
                status, record = request('/analyses', body={'url': 'BAHKmi4F1L8'})
            self.assertEqual(status, 202)
            aid = record['analysis_id']
            deadline = time.monotonic()+5
            while library.get(aid)['status'] in ('queued', 'running') and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(library.get(aid)['status'], 'ready')
            self.assertEqual(request('/bootstrap', scope=aid)[1]['is_example'], False)
            self.assertEqual(request('/bootstrap', user='bob', scope=aid)[0], 404)
            self.assertEqual(len(request('/analyses', user='bob')[1]['analyses']), 1)
            self.assertEqual(request('/profile', body={'initial_opinion': 'Example view'}, method='PATCH')[0], 200)
            self.assertEqual(request('/profile', scope=aid, body={'initial_opinion': 'New video view'}, method='PATCH')[0], 200)
            self.assertEqual(request('/bootstrap')[1]['profile']['initial_opinion'], 'Example view')
            self.assertEqual(request('/bootstrap', scope=aid)[1]['profile']['initial_opinion'], 'New video view')
            status, room = request('/rooms', scope=aid, body={'participants': ['g1'], 'initial_opinion': 'New video view'})
            self.assertEqual(status, 201)
            self.assertEqual(request('/rooms/'+room['room_id'])[0], 404)
            self.assertEqual(request('/rooms/'+room['room_id'], scope=aid)[0], 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            accounts.close()


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.example = self.root/'example'
        write_json(self.example/'04_web/catalog.json', {'video': {'video_id': 'BAHKmi4F1L8', 'title': 'Existing example'},
                                                       'agents': [{}, {}], 'counts': {'collected': 10}})
        self.release = threading.Event()
        self.calls = 0
        self.runner_error = None
        def runner(root, record, settings, update):
            self.calls += 1
            update(stage='collect', collected_count=17)
            self.release.wait(2)
            if self.runner_error:
                raise self.runner_error
            update(stage='presentation', agent_count=2)
        self.library = AnalysisLibrary(self.root/'runs', self.example, {'YOUTUBE_API_KEY': 'test'}, runner=runner)
        self.client_patch = patch('analysis_pipeline.create_client', return_value=PipelineClient())
        self.client_patch.start()

    def tearDown(self):
        self.release.set()
        self.library.executor.shutdown(wait=True)
        self.client_patch.stop()
        self.tmp.cleanup()

    def wait(self, aid):
        deadline = time.monotonic()+3
        while self.library.get(aid)['status'] in ('queued', 'running'):
            if time.monotonic() > deadline:
                self.fail('Analysis did not finish.')
            time.sleep(.005)
        return self.library.get(aid)

    def start(self, **options):
        return self.library.start({'url': 'https://youtu.be/BAHKmi4F1L8', **options})

    def test_duplicate_requests_share_job_and_refresh_creates_a_separate_snapshot(self):
        first = self.start()
        self.assertEqual(self.start()['analysis_id'], first['analysis_id'])
        self.assertEqual(self.start(refresh=True)['analysis_id'], first['analysis_id'])
        self.release.set()
        self.assertEqual(self.wait(first['analysis_id'])['status'], 'ready')
        self.assertEqual(self.start()['analysis_id'], first['analysis_id'])
        second = self.start(refresh=True)
        self.assertNotEqual(second['analysis_id'], first['analysis_id'])
        self.assertEqual(self.wait(second['analysis_id'])['status'], 'ready')
        factory = Mock(side_effect=lambda path: path)
        self.assertNotEqual(self.library.application(first['analysis_id'], factory), self.library.application(second['analysis_id'], factory))
        self.assertEqual(len(self.library.listing()['analyses']), 3)

    def test_failed_jobs_retry_and_never_expose_provider_payloads(self):
        self.runner_error = YouTubeError('commentsDisabled', 'secret-key-private-payload')
        self.release.set()
        record = self.start()
        failed = self.wait(record['analysis_id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('disabled', failed['error'])
        self.assertNotIn('secret-key', json.dumps(self.library.listing()))
        self.runner_error = None
        self.library.retry(record['analysis_id'])
        self.assertEqual(self.wait(record['analysis_id'])['status'], 'ready')
        self.assertEqual(self.calls, 2)

    def test_server_restart_preserves_progress_and_requires_explicit_resume(self):
        self.release.set()
        record = self.start()
        self.wait(record['analysis_id'])
        self.library.update(record['analysis_id'], status='running')
        restored = AnalysisLibrary(self.library.root, self.example, {})
        try:
            state = restored.get(record['analysis_id'])
            self.assertEqual(state['status'], 'interrupted')
            self.assertEqual(state['collected_count'], 17)
            self.assertEqual(state['agent_count'], 2)
        finally:
            restored.close()

    def test_invalid_settings_and_unready_or_foreign_analysis_are_rejected(self):
        for options in ({'max_comments': True}, {'max_comments': 2001}, {'with_replies': 'yes'}):
            with self.assertRaises(AnalysisError):
                self.start(**options)
        with self.assertRaises(FileNotFoundError):
            self.library.get('../.env')
        record = self.start()
        with self.assertRaises(AnalysisError):
            self.library.application(record['analysis_id'], Mock())
        self.assertEqual(self.library.get('example')['status'], 'ready')


if __name__ == '__main__':
    unittest.main()
