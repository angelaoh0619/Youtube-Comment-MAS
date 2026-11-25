"""Prepare a new fictional walkthrough using real comment-grounded agents.

The opinions and questions are authored for this demo. No visitor or owner
conversation history is read. Agent replies and reflection are generated once
using the existing public YouTube comment analysis.
"""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from filter_comments import write_json
from llm_client import create_client, read_settings
from perspective_agents import ChatSession, clone
from web_data import DEFAULT_DATA
from web_server import Application

INITIAL = (
    'I support a four-day workweek with the same pay. A full extra day away from work '
    'seems like the clearest way to rest and spend time with people I care about. '
    'If we focus better during the week, I expect most workplaces could make it work.\n\n'
    'I have not thought much about jobs that need people on duty every day. '
    'I also assume that fewer workdays would mean fewer hours of work.'
)
CURRENT = (
    'I still value a full day away from work, and keeping pay stable remains important to me. '
    'But I no longer think a four-day schedule is automatically the best option for everyone.\n\n'
    'I would compare a full day off with shorter daily hours, especially for people with regular '
    'care responsibilities. I would also check whether total hours really fall, overtime is paid, '
    'and the people covering essential services share the benefit. Fixing unpaid overtime '
    'should not wait for a new weekly schedule.\n\n'
    'I would judge a pilot by workers’ take-home pay, recorded hours, the workload of the '
    'people on duty, access to services, and what happens to output and jobs. A free weekday '
    'and earlier evenings solve different problems, so workers should have a say in the choice.\n\n'
    'The comments helped me see these trade-offs, but they do not establish which staffing plan '
    'would work, who would cover extra costs, or whether productivity would stay the same.'
)


def build():
    client = create_client(read_settings())
    working = ROOT/'.deploy/example-build'
    working.mkdir(parents=True, exist_ok=True)
    app = Application(DEFAULT_DATA, client, output=working/'04_web')
    rooms = {}
    try:
        def room(name, participants, title):
            rid = uuid.uuid5(uuid.NAMESPACE_URL, 'commentmas:fictional-walkthrough:v2:'+name).hex
            result = ChatSession(app.data.bundle, app.rooms_dir/f'{rid}.json', participants, INITIAL, language='en')
            result.state.update(web_title=title, web_paused=True, web_auto_turns=0)
            result.save()
            rooms[rid] = result
            return result

        def ask_once(session, question, recipients=None):
            ids = recipients or session.state['participants']
            target = next((m for m in session.state['messages'] if m['role'] == 'user' and m['text'] == question), None)
            if target:
                if 'recipient_ids' in target and target['recipient_ids'] != ids:
                    raise ValueError('A prepared question must keep its original recipients.')
                target['recipient_ids'] = list(ids)
                session.save()
                result = session.answer(target['message_id'], ids, client)
            else:
                result = session.ask(question, client, ids, retrieval_query=app.data.retrieval_query(question, 'en'), language='en')
            if result['errors']:
                raise RuntimeError('A demo agent could not finish; rerun to resume its saved turn.')
            app.translate_replies(result['responses'])
            print('Prepared question: '+question, flush=True)
            return result

        single = room('whole-day-off', ['g1'], 'What does a whole day off change?')
        ask_once(single, 'What does a full day off offer that a shorter workday does not?')
        ask_once(single, 'What would make a four-day week less helpful even if the schedule looks shorter?')
        ask_once(single, 'If a full day off matters most to you, what compromise would you accept for a workplace that cannot close?')

        daily = room('everyday-care', ['g2'], 'A free Friday or time back every evening?')
        ask_once(daily, 'Why might finishing earlier every day matter more than having Friday off?')
        ask_once(daily, 'Could two workers doing the same job reasonably prefer different schedules?')
        ask_once(daily, 'What would you ask a parent or caregiver before choosing a shorter-week arrangement?')

        economics = room('pay-and-feasibility', ['g5'], 'What does keeping the same pay really mean?')
        ask_once(economics, 'I assumed better focus would make up for fewer hours. Why are you cautious about that?')
        ask_once(economics, 'What does keeping the same pay mean for someone who depends on overtime income?')
        ask_once(economics, 'Which outcomes would you watch in a trial, and which questions need evidence beyond these comments?')

        group = room('tradeoffs', ['g2', 'g4', 'g3', 'g5'], 'Who benefits, and who covers the gap?')
        opening = ask_once(group, 'I assumed a four-day week would help almost everyone. What am I overlooking?')
        opening_id = opening['target_message_id']
        history = clone(group.state['messages'][:5])
        first = [m for m in history if m['role'] == 'agent' and m['reply_to'] == opening_id]
        for index, aid in enumerate(group.state['participants']):
            target = next(m for m in first[index+1:]+first[:index+1] if m['sender_id'] != aid)
            result = group.answer(target['message_id'], [aid], client, history_snapshot=history)
            if result['errors']:
                raise RuntimeError('A demo discussion turn failed; rerun to resume it.')
            app.translate_replies(result['responses'])
        ask_once(group, 'What would you check before calling a pilot successful, and what can these comments not tell us?', ['g4', 'g5'])
        ask_once(group, 'Shorter days and overtime reform both sound useful. Where do your priorities overlap, and where do they differ?', ['g2', 'g3'])
        ask_once(group, 'If a clinic uses staggered days off, how would you keep the remaining staff from carrying the extra burden?', ['g4', 'g5'])

        all_views = room('designing-a-fair-trial', ['g1', 'g2', 'g3', 'g4', 'g5'], 'Designing a trial that works for more people')
        ask_once(all_views, 'Suppose we can test one change first. What would each of you protect before agreeing to a trial?')
        ask_once(all_views, 'What does a fair choice look like for caregivers and the people who keep services open?', ['g2', 'g4'])
        ask_once(all_views, 'Which pay and working-hours safeguards would need to be in place before the trial starts?', ['g3', 'g5'])
        ask_once(all_views, 'I still like a full day off, but now see that one schedule will not fit everyone. What should I keep open rather than assume?')
        for session in rooms.values():
            session.state.update(web_paused=True, web_auto_turns=0)
            session.save()
        reflection = app.reflect(INITIAL, CURRENT)
        if not reflection['items'] or not any(item.get('moment') for item in reflection['items']):
            raise RuntimeError('The demo reflection needs a linked conversation moment.')
        alignment = app.data.alignment(INITIAL)
        comparisons = {aid: app.data.compare(aid, INITIAL) for aid in app.data.profiles}
        snapshot = {'version': 3, 'source_fingerprint': app.data.fingerprint,
                    'bundle_sha256': app.data.bundle['meta']['content_sha256'],
                    'initial_opinion': INITIAL, 'current_view': CURRENT,
                    'default_room_id': single.path.stem,
                    'rooms': {rid: clone(session.state) for rid, session in rooms.items()},
                    'reflection': reflection, 'alignment': alignment, 'comparisons': comparisons,
                    'provenance': 'New fictional opinions and questions prepared for demonstration; agent replies and reflection generated from the public comment analysis. No personal conversation history is included.'}
        output = ROOT/'examples/four-day-week.json'
        write_json(output, snapshot)
        print(f'Prepared fictional walkthrough: {len(rooms)} conversations, {sum(len(s.state["messages"]) for s in rooms.values())} messages, {len(reflection["items"])} reflection observations -> {output}', flush=True)
    finally:
        app.executor.shutdown(wait=True)
        app.titles.shutdown(wait=True)


if __name__ == '__main__':
    build()
