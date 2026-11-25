"""An immutable, explicitly curated example, separate from each visitor's work."""
import json
from pathlib import Path

from filter_comments import digest
from group_comments import require
from perspective_agents import ChatSession, clone
from web_data import ROOT, WebData


class NoModel:
    def structured(self, *args, **kwargs):
        raise ValueError('The recorded example only uses prepared content.')


def snapshot_path(root):
    deployed = Path(root)/'04_web/example_journey.json'
    return deployed if deployed.exists() else ROOT/'examples/four-day-week.json'


def available(root):
    try:
        snapshot = json.loads(snapshot_path(root).read_text())
        catalog = json.loads((Path(root)/'04_web/catalog.json').read_text())
        return snapshot['source_fingerprint'] == catalog['fingerprint']
    except (OSError, ValueError, KeyError, TypeError):
        return False


class RecordedStore:
    def __init__(self, snapshot):
        self.records = {'rooms/'+rid: room for rid, room in snapshot['rooms'].items()}
        self.records['profile/state'] = {'initial_opinion': snapshot['initial_opinion'], 'saved_evidence': []}

    def load(self, key):
        return clone(self.records.get(key))

    def list_ids(self, collection):
        return [key.split('/')[1] for key in self.records if key.startswith(collection+'/')]

    def save(self, *args, **kwargs):
        raise ValueError('This is a recorded example. Start your own session to make changes.')

    delete = save


class RecordedData(WebData):
    def __init__(self, root):
        super().__init__(root, NoModel())
        self.snapshot = json.loads(snapshot_path(root).read_text())
        sample = self.snapshot
        require(sample['source_fingerprint'] == self.fingerprint and sample['bundle_sha256'] == self.bundle['meta']['content_sha256'], 'Recorded example does not match its source analysis.')
        require(sample['default_room_id'] in sample['rooms'], 'Missing recorded conversation.')
        store = RecordedStore(sample)
        for rid, state in sample['rooms'].items():
            require(state['initial_opinion'] == sample['initial_opinion'] and state.get('web_paused') is True, 'Recorded conversations must share the initial view and stay paused.')
            ChatSession(self.bundle, self.output/'rooms'/f'{rid}.json', storage=store)
        require(set(sample['comparisons']) == set(self.profiles), 'Every perspective needs a prepared comparison.')
        for item in sample['reflection']['items']:
            require(not item['before_quote'] or item['before_quote'] in sample['initial_opinion'], 'Recorded reflection quotes a different initial view.')
            require(not item['now_quote'] or item['now_quote'] in sample['current_view'], 'Recorded reflection quotes a different current view.')
            moment = item.get('moment')
            if moment:
                state = sample['rooms'].get(moment['room_id'])
                require(state is not None, 'Reflection points outside the recorded example.')
                message = next((m for m in state['messages'] if m['message_id'] == moment['message_id'] and m['role'] == 'agent'), None)
                require(message is not None and moment['quote'] in message['text'], 'Recorded discussion quote is not exact.')
                require(not moment['user_quote'] or any(moment['user_quote'] in m['text'] for m in state['messages'] if m['role'] == 'user'), 'Recorded user quote is not exact.')

    def catalog(self):
        catalog = super().catalog()
        sample = self.snapshot
        catalog.update(fingerprint=digest(['recorded-example-v1', sample]), read_only=True,
                       walkthrough={k: clone(sample[k]) for k in ('initial_opinion', 'current_view', 'default_room_id', 'reflection')})
        return catalog

    def alignment(self, opinion):
        require(opinion == self.snapshot['initial_opinion'], 'The recorded example has a fixed initial view.')
        return clone(self.snapshot['alignment'])

    def compare(self, aid, opinion):
        require(opinion == self.snapshot['initial_opinion'] and aid in self.snapshot['comparisons'], 'Choose a recorded perspective.')
        return clone(self.snapshot['comparisons'][aid])

    def comments(self, originals):
        result = []
        for comment in originals:
            translation = self.translator.cache.get(digest(['en', comment['text']]))
            result.append({**self.comment(comment, translation or comment['text']), 'translation_pending': translation is None})
        return result
