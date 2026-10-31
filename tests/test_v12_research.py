"""V1.2 contracts, isolated PostgreSQL and synthetic provider responses only."""
import copy
import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import delete, event

from alphalab.ai import AI
from alphalab.company_report import (SUMMARY_FIELDS, SUMMARY_SYSTEM, SECTIONS, parse_summary,
                                     parse_report, payload, summary_payload, summary_key, request_key)
from alphalab.config import UserError
from alphalab.data import MarketData, read_home_sections
from alphalab.db import cache, now
from alphalab.research_context import build_context, fingerprint
from alphalab.stock_chat import stored_turns, MAX_HISTORY_CHARS, MAX_HISTORY_BYTES
from test_company_research import FakeClient, sample_context, report_text
from test_terminal_ui import seed_research, launch, search


def summary_text(message='合成夹具，不是投资结论'):
    summary = {key: message for key in SUMMARY_FIELDS}
    summary.update(opinion='数据不足', facts=['合成资料；测试源；2026-10-30'],
                   risks=['缺少可靠估值'], change_conditions=['新的可核对披露'])
    return json.dumps({'summary': summary}, ensure_ascii=False)


class SummaryClient(FakeClient):
    text = summary_text()
    calls = []


@pytest.fixture(autouse=True)
def reset_clients():
    SummaryClient.calls = []
    SummaryClient.text = summary_text()
    FakeClient.calls = []
    FakeClient.text = None


def test_summary_only_contract_and_independent_full_cache(system, monkeypatch):
    settings, _, _, repo = system
    context = sample_context()
    monkeypatch.setattr(repo, 'memory', lambda *a, **k: pytest.fail('No unrelated memory'))
    summary, cached = AI(repo, settings, SummaryClient).company_summary(context)
    assert not cached and set(summary['report']) == {'summary'}
    assert summary['report']['summary']['opinion'] == '数据不足'
    sent = SummaryClient.calls[0]
    assert sent['messages'][0]['content'] == SUMMARY_SYSTEM
    assert sent['max_tokens'] == 1600 and sent['response_format'] == {'type': 'json_object'}
    assert '不得生成sections' in sent['messages'][0]['content']
    service = AI(repo, settings, FakeClient)
    assert service.saved_company_report(context) is None
    full, cached = service.company_report(context)
    assert not cached and set(full['report']) == {'sections'}
    assert len(FakeClient.calls) == 1 and len(SummaryClient.calls) == 1
    assert service.company_report(context) == (full, True)
    assert AI(repo, settings, SummaryClient).company_summary(context) == (summary, True)
    assert request_key(context, settings.deepseek_model) != summary_key(context, settings.deepseek_model)
    changed = copy.deepcopy(context)
    changed['financial_summary']['营业收入']['value'] += 1
    AI(repo, settings, SummaryClient).company_summary(changed)
    assert service.saved_company_report(changed) is None
    assert repo.latest_company_report('600519', kind='full') == full
    assert service.saved_company_report(context) == full
    assert len(repo.list('research_reports')) == 3


@pytest.mark.parametrize('change', ['sections', 'extra_facts', 'extra_risks', 'extra_conditions', 'opinion', 'empty'])
def test_summary_validation(change):
    obj = json.loads(summary_text())
    if change == 'sections':obj['sections'] = []
    elif change == 'extra_facts':obj['summary']['facts'] *= 6
    elif change == 'extra_risks':obj['summary']['risks'] *= 4
    elif change == 'extra_conditions':obj['summary']['change_conditions'] *= 4
    elif change == 'opinion':obj['summary']['opinion'] = '必涨'
    else:obj['summary']['judgment'] = ''
    with pytest.raises(ValueError):parse_summary(json.dumps(obj))


def test_legacy_combined_report_reuse_and_reading(system):
    settings, _, _, repo = system
    context = sample_context()
    legacy = json.loads(report_text())
    legacy['summary'] = json.loads(summary_text())['summary']
    assert parse_report(json.dumps(legacy)) == legacy
    saved = payload(context, json.dumps(legacy), settings.deepseek_model, now().isoformat())
    repo.put('research_reports', 'old-combined-key', saved)
    service = AI(repo, settings, SummaryClient)
    assert service.company_summary(context) == (saved, True)
    assert service.company_report(context) == (saved, True)
    assert not SummaryClient.calls


def test_followup_scoped_bounded_no_sections_failure_retains_history(system, monkeypatch):
    settings, _, admin, repo = system
    context = sample_context()
    AI(repo, settings, SummaryClient).company_summary(context)
    monkeypatch.setattr(repo, 'memory', lambda *a, **k: pytest.fail('Do not load unrelated memories'))
    repo.put('user_preferences', 'profile', {'period': '长期', 'goal': '核对现金流'})
    class ChatClient(FakeClient):
        text = '合成资料不足，请核对经营现金流及报告期。'
        calls = []
    service = AI(repo, settings, ChatClient)
    for i in range(6):assert service.stock_followup(context, '合成问题'+str(i)) == ChatClient.text
    turns = service.stock_history('600519')
    assert len(turns) == 4 and turns[0]['question'] == '合成问题2'
    assert service.stock_history('600001') == []
    assert AI(admin, settings, ChatClient).stock_history('600519') == []
    sent = json.loads(ChatClient.calls[-1]['messages'][1]['content'])
    assert sent['memory'] == []
    evidence = sent['evidence']
    assert len(evidence['history']) == 4
    assert evidence['research_preferences']['period'] == '长期'
    assert 'sections' not in evidence['latest_summary']
    assert evidence['research_context'] == context
    assert len(repo.list('research_reports')) == 1  # Chat does not pollute report library.
    class Failure(ChatClient):
        def post(self, *a, **k):raise httpx.ReadTimeout('PRIVATE_ERROR')
    with pytest.raises(UserError):AI(repo, settings, Failure).stock_followup(context, '失败问题')
    assert service.stock_history('600519') == turns
    assert AI(repo, settings).saved_company_summary(context)
    with pytest.raises(UserError, match='预算'):
        AI(repo, replace(settings, daily_budget=Decimal(0)), ChatClient).stock_followup(context, '预算问题')
    assert service.stock_history('600519') == turns


def test_history_character_and_byte_limits():
    turns = stored_turns([{'question': '问'*1000, 'answer': '答'*9000} for _ in range(10)])
    encoded = json.dumps(turns, ensure_ascii=False)
    assert 0 < len(turns) <= 4 and len(encoded) <= MAX_HISTORY_CHARS and len(encoded.encode()) <= MAX_HISTORY_BYTES


def test_lazy_history_independent_retry_and_financial_business_fetch(system, monkeypatch):
    import pandas as pd
    from alphalab import provider
    from alphalab.ui.reads import CachedResearch
    _, auth, _, _ = system
    seed_research(auth)
    with auth.db.begin() as c:
        c.execute(delete(cache).where(cache.c.key.startswith('history:') | cache.c.key.startswith('financial:') | cache.c.key.startswith('business:')))
    calls = []
    fail = [True]
    def upstream(name, **kwargs):
        calls.append(name)
        if name == 'stock_zh_a_daily':
            if fail[0]:raise RuntimeError('private error')
            return pd.DataFrame([{'date': '2026-10-30', 'close': 10, 'open': 10, 'high': 11, 'low': 9, 'volume': 1}])
        if name == 'sina_financial_summary':return pd.DataFrame([{'指标': '净利润(元)', '20260930': -100000000}])
        if name == 'stock_zygc_em':return pd.DataFrame([{'主营构成': '合成产品', '主营收入': 10, '报告日期': '2026-06-30'}])
        pytest.fail(name)
    monkeypatch.setattr(provider, 'call', upstream)
    reads = []
    original = CachedResearch.history
    def track(self, *args, **kwargs):
        reads.append('history');return original(self, *args, **kwargs)
    monkeypatch.setattr(CachedResearch, 'history', track)
    app = search(launch(system, monkeypatch))
    assert not calls and not reads
    app.radio(key='research_tab').set_value('财务').run()
    assert not calls and not reads
    assert any(b.label == '获取财务' for b in app.button)
    app.radio(key='research_tab').set_value('走势').run()
    assert not calls and not app.get('plotly_chart')
    next(b for b in app.button if b.label == '获取走势').click().run()
    assert calls == ['stock_zh_a_daily'] and app.warning
    fail[0] = False
    app.run()
    next(b for b in app.button if b.label == '重试获取走势').click().run()
    assert len(app.get('plotly_chart')) == 1 and calls == ['stock_zh_a_daily']*2
    app.radio(key='research_tab').set_value('财务').run()
    next(b for b in app.button if b.label == '获取财务').click().run()
    assert calls[-1] == 'sina_financial_summary' and len(calls) == 3
    assert any('-1.00 亿元' in x.proto.body and 'risk' in x.proto.body for x in app.get('html'))
    app.radio(key='research_tab').set_value('主营').run()
    next(b for b in app.button if b.label == '获取主营').click().run()
    assert calls[-1] == 'stock_zygc_em' and len(calls) == 4 and len(app.dataframe) == 1
    app.radio(key='research_tab').set_value('走势').run()
    assert len(app.get('plotly_chart')) == 1 and len(calls) == 4 and not app.exception


def test_home_does_not_read_unused_spot():
    class Home:
        def indices(self):return {'items': []}
        def policies(self):return {'items': []}
        def spot(self):pytest.fail('Unused spot')
    assert set(read_home_sections(Home())) == {'indices', 'policies'}


def test_financial_display_units_preserve_raw_values():
    from alphalab.ui.components import financial_value, financial_tone
    assert financial_value('净利润', -123400000, '归母净利润（元）') == '-1.23 亿元'
    assert financial_value('营业收入', 123400000, '营业收入') == '123,400,000.00'
    assert financial_value('ROE', -2, '净资产收益率(%)') == '-2.00 %'
    assert financial_tone('净利润', -1) == 'risk'


def test_summary_ui_library_full_on_click_and_followup(system, monkeypatch):
    settings, auth, _, repo = system
    seed_research(auth)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-not-real-key')
    class Routed(FakeClient):
        calls = []
        def post(self, url, **kwargs):
            system_text = kwargs['json']['messages'][0]['content']
            self.text = summary_text() if '不得生成sections' in system_text else report_text() if '只有sections字段' in system_text else '合成追问回答'
            return super().post(url, **kwargs)
    original = AI.__init__
    monkeypatch.setattr(AI, '__init__', lambda self, repo, settings: original(self, repo, settings, Routed))
    app = search(launch(system, monkeypatch))
    app.radio(key='research_tab').set_value('AI研究').run()
    assert not Routed.calls
    next(b for b in app.button if b.label == '生成AI研究').click().run()
    assert len(Routed.calls) == 1 and '精简研究摘要' in {x.value for x in app.subheader}
    assert not set(SECTIONS).intersection(x.value for x in app.subheader)
    app.run()
    assert len(Routed.calls) == 1
    app.text_area(key='question_stock_600519').input('合成公司的主要缺口？')
    next(b for b in app.button if b.label == '发送问题').click().run()
    assert len(Routed.calls) == 2 and len(AI(repo, settings).stock_history('600519')) == 1
    next(b for b in app.button if b.label == '生成完整研究依据').click().run()
    assert len(Routed.calls) == 3 and set(SECTIONS) <= {x.value for x in app.subheader}
    next(b for b in app.button if b.label == '生成完整研究依据').click().run()
    assert len(Routed.calls) == 3  # Same context full reuse.
    app.radio(key='navigation').set_value('AI研究').run()
    for button in list(app.button):
        if button.label == '阅读报告':
            button.click().run()
            assert not app.error and not app.exception
            break
    assert len(Routed.calls) == 3


def test_report_status_projection_and_recommendation_reuse(system, monkeypatch):
    import alphalab.ui.recommendations as module
    _, auth, _, repo = system
    seed_research(auth)
    repo.put('user_preferences', 'profile', {'level': '零基础', 'industries': [], 'period': '长期', 'onboarding_completed': True})
    calls = []
    original = module.recommend
    monkeypatch.setattr(module, 'recommend', lambda *a, **k: (calls.append(1), original(*a, **k))[1])
    app = launch(system, monkeypatch)
    assert len(calls) == 1
    app.run()
    assert len(calls) == 1
    MarketData(auth.db).cached('financial:600519', 3600, '测试财务', lambda: {'items': [{'指标': '净利润(元)', '20260930': 1}]}, refresh=True)
    app.run()
    assert len(calls) == 2
    repo.put('user_preferences', 'profile', {'level': '零基础', 'industries': [], 'period': '短期', 'onboarding_completed': True})
    app.run()
    assert len(calls) == 3
    sql = []
    def executed(conn, cursor, statement, *a):sql.append(statement)
    event.listen(repo.db, 'before_cursor_execute', executed)
    try:repo.report_index(['600519'])
    finally:event.remove(repo.db, 'before_cursor_execute', executed)
    query = next(q for q in sql if 'research_reports' in q)
    assert 'research_reports.payload AS' not in query and 'research_reports.payload ->>' in query


def test_summary_failure_preserves_existing_summary_full_and_private_scope(system):
    settings, _, admin, repo = system
    context = sample_context()
    summary, _ = AI(repo, settings, SummaryClient).company_summary(context)
    full, _ = AI(repo, settings, FakeClient).company_report(context)
    assert AI(admin, settings).saved_company_summary(context) is None
    class Failed(SummaryClient):
        text = '{"summary": {"opinion": "必涨"}}'
    with pytest.raises(UserError):AI(repo, settings, Failed).company_summary(context, regenerate=True)
    assert AI(repo, settings).saved_company_summary(context) == summary
    assert AI(repo, settings).saved_company_report(context) == full
    assert len(repo.list('research_reports')) == 2
