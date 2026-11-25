import copy
import json
import shutil
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from filter_comments import write_json
from perspective_agents import ChatSession, clone
from recorded_example import NoModel, RecordedData, RecordedStore, available
from web_data import DEFAULT_DATA, WebData
from web_server import Application, Handler


class RecordedExampleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for relative in ('01_filter/filtered.json', '02_group/groups.json', '03_agents/agents.json', '04_web/catalog.json', '04_web/translations.json'):
            target = self.root/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(DEFAULT_DATA/relative, target)
        self.data = WebData(self.root, NoModel())
        self.rid = 'a'*32
        initial, current = 'A fictional initial opinion.', 'A more conditional fictional opinion.'
        room = ChatSession(self.data.bundle, self.root/'scratch'/f'{self.rid}.json', ['g1'], initial, language='en')
        question = room.append('user', 'user', 'What am I overlooking?', language='en')
        evidence = clone(self.data.bundle['agents'][0]['comments'][0])
        answer = 'A grounded demonstration answer.'
        room.append('agent', 'g1', answer, question['message_id'],
                    segments=[{'text': answer, 'basis': 'comment', 'comment_ids': [evidence['comment_id']]}],
                    evidence=[evidence], retrieved_comment_ids=[evidence['comment_id']], follow_up_questions=[])
        room.state.update(web_paused=True, web_title='A fictional discussion')
        self.sample = {'version': 2, 'source_fingerprint': self.data.fingerprint,
                       'bundle_sha256': self.data.bundle['meta']['content_sha256'],
                       'initial_opinion': initial, 'current_view': current, 'default_room_id': self.rid,
                       'rooms': {self.rid: room.state},
                       'reflection': {'before_excerpt': initial, 'after_excerpt': current, 'one_to_one': 1, 'group': 0,
                                      'items': [{'category': 'changed', 'title': 'A more conditional view', 'explanation': 'An example interpretation.',
                                                 'before_quote': initial, 'now_quote': current,
                                                 'moment': {'room_id': self.rid, 'message_id': 'm0002', 'quote': answer,
                                                            'speaker': 'Example perspective', 'room_type': 'one-to-one chat', 'user_quote': question['text']}}]},
                       'alignment': {'agents': []},
                       'comparisons': {aid: {'similar': 'A shared point.', 'different': 'A difference.', 'consideration': 'An open question.', 'similar_quotes': [], 'different_quotes': []} for aid in self.data.profiles}}
        self.write_sample(self.sample)
        self.app = Application(self.root, NoModel())

    def write_sample(self, sample):
        write_json(self.root/'04_web/example_journey.json', sample)

    def tearDown(self):
        self.app.executor.shutdown(wait=True)
        self.app.titles.shutdown(wait=True)
        self.tmp.cleanup()

    def test_read_only_example_uses_fixed_content_and_prepared_comparisons(self):
        self.assertTrue(available(self.root))
        data = RecordedData(self.root)
        self.assertTrue(data.catalog()['read_only'])
        self.assertNotEqual(data.catalog()['fingerprint'], self.data.fingerprint)
        self.assertEqual(data.catalog()['walkthrough']['current_view'], self.sample['current_view'])
        self.assertEqual(data.compare('g1', self.sample['initial_opinion'])['similar'], 'A shared point.')
        with self.assertRaises(ValueError):
            data.compare('g1', 'Another opinion')
        store = RecordedStore(self.sample)
        with self.assertRaises(ValueError):
            store.save('profile/state', {}, None)
        first = store.load('rooms/'+self.rid)
        first['messages'].clear()
        self.assertEqual(len(store.load('rooms/'+self.rid)['messages']), 2)

    def test_reflection_links_and_quotes_cannot_point_to_other_conversations(self):
        changed = copy.deepcopy(self.sample)
        changed['reflection']['items'][0]['moment']['room_id'] = 'b'*32
        self.write_sample(changed)
        with self.assertRaises(ValueError):
            RecordedData(self.root)
        changed = copy.deepcopy(self.sample)
        changed['reflection']['items'][0]['moment']['quote'] = 'Not in the answer'
        self.write_sample(changed)
        with self.assertRaises(ValueError):
            RecordedData(self.root)

    def test_http_example_is_immutable_and_does_not_seed_personal_records(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.app, server.example_data, server.library = self.app, self.root, None
        server.allowed_origins = set()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, body=None, method=None, scope='walkthrough'):
            headers = {'X-Analysis-ID': scope}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            req = Request(f'http://127.0.0.1:{server.server_port}/api'+path, headers=headers, method=method,
                          data=json.dumps(body).encode() if body is not None else None)
            try:
                with urlopen(req, timeout=5) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                with exc:
                    return exc.code, json.load(exc)
        try:
            self.assertTrue(request('/analyses')[1]['analyses'][0]['has_walkthrough'])
            status, data = request('/bootstrap')
            self.assertEqual(status, 200)
            self.assertEqual(data['profile']['initial_opinion'], self.sample['initial_opinion'])
            self.assertEqual(len(data['rooms']), 1)
            self.assertTrue(request('/rooms/'+self.rid)[1]['paused'])
            for path, body, method in (('/rooms', {'participants': ['g1']}, 'POST'),
                                       ('/profile', {'initial_opinion': 'Overwrite'}, 'PATCH'),
                                       ('/rooms/'+self.rid, None, 'DELETE'),
                                       ('/rooms/'+self.rid+'/ask', {'text': 'A new question'}, 'POST'),
                                       ('/reflect', {'current_view': 'Change'}, 'POST'),
                                       ('/reflections', {}, 'POST')):
                self.assertEqual(request(path, body, method)[0], 403)
            status, job = request('/compare', {'agent_id': 'g1', 'initial_opinion': self.sample['initial_opinion'], 'request_id': 'sample-comparison'})
            self.assertEqual(status, 202)
            deadline = time.monotonic()+2
            while job['status'] == 'running' and time.monotonic() < deadline:
                job = request('/jobs/'+job['job_id'])[1]
            self.assertEqual(job['status'], 'completed')
            self.assertEqual(request('/bootstrap', scope='example')[1]['rooms'], [])
            self.assertEqual(self.app.profile(), {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            if getattr(server, 'recorded_app', None):
                server.recorded_app.executor.shutdown(wait=True)
                server.recorded_app.titles.shutdown(wait=True)
