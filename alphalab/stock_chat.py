"""Bounded single-stock conversation contract, backed by existing private chat_messages."""
import json
import re
from .config import UserError
from .research_context import fingerprint

MAX_TURNS = 4
MAX_HISTORY_CHARS = 5000
MAX_HISTORY_BYTES = 14000


def validate_code(code):
    if not isinstance(code, str) or not re.fullmatch(r'\d{6}', code):raise UserError('股票代码无效。')


def stored_turns(turns):
    result = []
    for turn in turns[-MAX_TURNS:]:
        if not isinstance(turn, dict):continue
        if not isinstance(turn.get('question'), str) or not isinstance(turn.get('answer'), str):continue
        result.append({'question': turn['question'][:1000], 'answer': turn['answer'][:3500],
                       'created_at': str(turn.get('created_at', ''))[:50]})
    while result:
        encoded = json.dumps(result, ensure_ascii=False)
        if len(encoded) <= MAX_HISTORY_CHARS and len(encoded.encode()) <= MAX_HISTORY_BYTES:break
        if len(result) > 1:result.pop(0)
        else:
            # Preserve the last successful pair within both limits.
            result[0]['answer'] = result[0]['answer'][:len(result[0]['answer'])//2]
            if not result[0]['answer']:return []
    return result


def history(record, code):
    validate_code(code)
    if not isinstance(record, dict) or record.get('code') != code:return []
    return stored_turns(record.get('turns', []) if isinstance(record.get('turns'), list) else [])


def evidence(context, report, profile, turns):
    # A summary wins over nine chapters; never forward a full report or its context snapshot.
    content = (report or {}).get('report', {})
    summary = content.get('summary')
    if summary is None:
        sections = content.get('sections', [])
        summary = next((s for s in sections if s.get('title') == '研究摘要'), None)
    if summary is not None:
        summary = json.dumps(summary, ensure_ascii=False)[:4000]
    return {'research_context': context, 'latest_summary': summary,
            'summary_context_fingerprint': (report or {}).get('context_fingerprint'),
            'summary_uses_earlier_data': bool(report and report.get('context_fingerprint') != fingerprint(context)),
            'research_preferences': {k: str(profile.get(k, ''))[:300] for k in ('industries', 'period', 'goal', 'level')},
            'history': stored_turns(turns),
            'scope': '仅讨论Research Context中的这一只股票；旧摘要与对话不得当作当前事实。'}
