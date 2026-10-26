"""Report validation, summaries, follow-up context, and timestamps."""
import datetime as dt
import json
import re


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def source_findings(source):
    for turn in [source] + list(reversed(source.get('turns', []))):
        if turn.get('findings'):
            return turn['findings']
    return []


def report_context(source, indexes=None):
    if indexes is not None:
        findings = source_findings(source)
        if not isinstance(indexes, list) or not indexes or any(type(i) is not int or i < 0 or i >= len(findings) for i in indexes) or len(set(indexes)) != len(indexes):
            raise ValueError('Select valid findings from the saved report.')
        context = 'Selected findings from an earlier report (verify them against the current source):\n' + json.dumps([findings[i] for i in indexes], ensure_ascii=False, indent=2)
        context += '\nScope is limited to these selected findings and the current user request.'
    else:
        turns = source.get('turns', []) + [source]
        context = 'Previous conversation, provided as context for this request:\n' + '\n\n'.join('User: '+t['task']+'\nReport: '+t.get('summary','') + ('\nClarification answers: '+json.dumps(t['clarifications'],ensure_ascii=False) if t.get('clarifications') else '') for t in turns)
    if len(context) > 90000:
        raise ValueError('This conversation is too long to carry forward. Start a new task with the relevant details.')
    return context


def plan_from_conversation(source):
    """The latest finished Plan report plus everything agreed in the chat after it, so it can be built without planning again."""
    turns = list(source.get('turns', [])) + [source]
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if turn.get('mode') == 'plan' and not turn.get('chat') and turn.get('status') == 'done' and (turn.get('summary') or '').strip():
            summary = turn['summary'].strip()
            agreed = [t for t in turns[index + 1:] if (t.get('chat') or t.get('mode') == 'observe') and t.get('status') == 'done'
                      and (t.get('task') or '').strip() and (t.get('summary') or '').strip()]
            if agreed:
                summary += ('\n\n---\n\n## Changes and decisions agreed in the conversation after this plan\n\n'
                            'These are part of what to build, and they take precedence over the plan above wherever they conflict.\n\n'
                            + '\n\n'.join(f"### {n}. You said\n\n{t['task'].strip()[:4000]}\n\nReply:\n\n{t['summary'].strip()[:4000]}" for n, t in enumerate(agreed, 1)))
            return dict(summary=summary[:60000], findings=turn.get('findings') or [], acceptance_checks=turn.get('acceptance_checks') or [])
    raise ValueError('This conversation has no finished plan to build.')


def reported_checks(report):
    match = re.search(r'```relay-checks\s*\n(.*?)```', report, re.S)
    if not match:return []
    try: checks = json.loads(match.group(1))
    except ValueError:return []
    if not isinstance(checks, list):return []
    return [dict(command=c['command'][:2000],status=c['status'],details=c.get('details','')[:4000]) for c in checks[:100] if isinstance(c,dict) and isinstance(c.get('command'),str) and c.get('status') in ('passed','failed','not_run') and isinstance(c.get('details',''),str)]


def report_metadata(result):
    return dict(overview=result.get('overview',''), next_actions=result.get('next_actions',[]))


def validate_questions(questions):
    if not isinstance(questions, list) or len(questions) > 5:
        raise ValueError('Observer may ask up to five questions at a time.')
    seen = set()
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError('Invalid clarification question.')
        ident, text, options = question.get('id'), question.get('question'), question.get('options', [])
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', ident) or ident in seen:
            raise ValueError('Clarification question IDs must be unique letters/digits/underscores/hyphens.')
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 1000:
            raise ValueError('Clarification questions must contain 1–1,000 characters.')
        if not isinstance(options, list) or len(options) > 5 or any(not isinstance(x, str) or not 0 < len(x.strip()) <= 200 for x in options):
            raise ValueError('Invalid clarification options.')
        seen.add(ident)
    return json.loads(json.dumps(questions))


def validate_review(result):
    if not isinstance(result, dict) or result.get('status') not in ['observed', 'approved', 'needs_changes']:
        raise ValueError('Invalid structured review status')
    if not isinstance(result.get('summary'), str) or not isinstance(result.get('findings'), list):
        raise ValueError('Invalid review content')
    if not isinstance(result.get('acceptance_checks'), list) or not all(isinstance(x, str) for x in result['acceptance_checks']):
        raise ValueError('Invalid acceptance checks')
    if 'overview' in result and not isinstance(result['overview'], str):
        raise ValueError('Invalid report overview')
    if 'next_actions' in result and (not isinstance(result['next_actions'], list) or not all(isinstance(x,str) for x in result['next_actions'])):
        raise ValueError('Invalid next actions')
    validate_questions(result.get('questions', []))
    if result['status'] != 'observed' and result.get('questions'):
        raise ValueError('Only observations may include clarification questions.')
    for finding in result['findings']:
        if not isinstance(finding, dict) or any(not isinstance(finding.get(k), str) or not finding[k].strip() for k in ['id', 'file', 'problem', 'evidence', 'requested_change']):
            raise ValueError('A review finding is missing supporting evidence')
    if any('priority' in f and f['priority'] not in ('critical','high','medium','low') for f in result['findings']):
        raise ValueError('Invalid finding priority')
    if result['status'] == 'approved' and result['findings']:
        raise ValueError('Review cannot approve while findings remain')
    if result['status'] == 'needs_changes' and not result['findings']:
        raise ValueError('Review requested changes without actionable findings')
