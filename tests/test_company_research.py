"""Company research V1 uses isolated PostgreSQL and fake AI; no production requests."""
import copy
import json
from dataclasses import replace
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from alphalab.ai import AI
from alphalab.company_report import SECTIONS, SYSTEM, parse_report, request_key
from alphalab.config import SetupRequired, UserError
from alphalab.db import usage, now
from alphalab.research_context import build_context, context_from_cache, fingerprint


def report_text(message='测试夹具分析，非真实投资结论'):
    return json.dumps({'sections': [{'title': title, 'facts': [], 'analysis': [message],
                                    'missing_data': ['上下文未提供经营现金流量净额']} for title in SECTIONS]}, ensure_ascii=False)


def sample_context():
    def data(rows):return {'items': rows, 'source': '测试夹具源', 'fetched_at': '2026-10-30T01:00:00+00:00', 'stale': True}
    return build_context({'code': '600519', 'name': '测试公司', 'exchange': 'SH', 'price': 999,
                          'DEEPSEEK_API_KEY': 'MUST-NOT-COPY'},
        data([{'行业': '暂无可靠数据', '上市时间': '2001-08-27'}]),
        data([{'指标': '营业收入（元）', '20260930': '1,234'}, {'指标': '净资产收益率（ROE）（%）', '20260930': 12}]),
        data([{'date': '2026-10-28', 'close': 100}, {'date': '2026-10-29', 'close': 101}]),
        data([{'主营构成': '测试产品', '主营收入': 100, '报告日期': '2026-06-30', 'secret_field': 'MUST-NOT-COPY'}]),
        data([{'title': '官方政策索引夹具', 'url': 'https://www.gov.cn/zhengce/test.htm', 'published_at': '2026-10-20'}]))


class FakeClient:
    calls = []
    text = None
    def __init__(self, **kwargs):
        assert kwargs['timeout'].connect == 10 and kwargs['timeout'].read == 60
    def __enter__(self):return self
    def __exit__(self, *a):pass
    def post(self, url, **kwargs):
        self.calls.append(kwargs['json'])
        assert url == 'https://api.deepseek.com/chat/completions'
        assert kwargs['headers']['Authorization'] == 'Bearer test-not-real-key'
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': self.text or report_text()}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 200}})


@pytest.fixture(autouse=True)
def reset_fake():
    FakeClient.calls = []
    FakeClient.text = None


def test_context_whitelists_missing_dates_units_and_fingerprint():
    context = sample_context()
    assert context['financial_summary']['营业收入']['value'] == 1234
    assert context['financial_summary']['营业收入']['date'] == '2026-09-30'
    assert context['financial_summary']['营业收入']['unit'] == '元'
    assert context['financial_summary']['经营现金流']['missing']
    assert context['financial_summary']['营业收入']['cached'] and context['financial_summary']['营业收入']['stale']
    assert context['company_profile']['total_shares']['missing']
    assert context['price_history_summary']['value']['last_close'] == 101
    assert context['policy_context']['value'][0]['published_at'] == '2026-10-20'
    assert context['policy_context']['coverage']['company_relevance_verified'] is False
    assert context['business_composition']['coverage']=={'included_rows':1,'cached_rows':1,'limit':15}
    assert {'PE', 'PB', '实时价格'} <= set(context['missing_data'])
    assert 'MUST-NOT-COPY' not in json.dumps(context)
    changed = copy.deepcopy(context)
    changed['financial_summary']['营业收入']['fetched_at'] = '2026-10-31'
    assert fingerprint(context) == fingerprint(changed)
    changed['financial_summary']['营业收入']['value'] = 5678
    assert fingerprint(context) != fingerprint(changed)
    assert fingerprint(dict(reversed(list(context.items())))) == fingerprint(context)


def test_builder_does_not_fetch_spot_or_other_live_sources():
    class CachedView:
        def __getattr__(self, name):
            assert name in ('company', 'financials', 'history', 'business', 'policies')
            def absent(*a):raise RuntimeError('cache absent')
            return absent
    context = context_from_cache(CachedView(), {'code': '600519', 'name': '测试公司'})
    assert context['financial_summary']['经营现金流']['missing']
    assert context['policy_context']['missing'] and context['data_cutoff'] is None


def test_durable_report_dedup_audit_regeneration_and_context_change(system, monkeypatch):
    settings, _, _, repo = system
    context = sample_context()
    monkeypatch.setattr(repo, 'memory', lambda *a, **k: pytest.fail('Company reports must not read chat memory'))
    service = AI(repo, settings, FakeClient)
    first, cached = service.company_report(context)
    assert not cached and len(FakeClient.calls) == 1
    assert first['context_snapshot'] == context
    assert first['context_fingerprint'] == fingerprint(context)
    assert first['data_cutoff'] == '2026-10-29' and first['provider'] == 'DeepSeek'
    assert 'test-not-real-key' not in json.dumps(first)
    assert [s['title'] for s in first['report']['sections']] == list(SECTIONS)
    # Persisted lookup survives a new service instance and calendar-day rollover.
    import alphalab.ai as module
    tomorrow = now()+timedelta(days=1)
    monkeypatch.setattr(module, 'now', lambda: tomorrow)
    second, cached = AI(repo, settings, FakeClient).company_report(context)
    assert cached and second == first and len(FakeClient.calls) == 1
    _, cached = service.company_report(context, regenerate=True)
    assert not cached and len(FakeClient.calls) == 2
    context['financial_summary']['营业收入']['value'] = 5678
    service.company_report(context)
    assert len(FakeClient.calls) == 3
    sent = FakeClient.calls[0]
    assert sent['response_format'] == {'type': 'json_object'} and sent['max_tokens'] == 3500
    assert sent['messages'][0]['content'] == SYSTEM
    assert json.loads(sent['messages'][1]['content'])['memory'] == []


def test_key_missing_cache_still_readable_and_user_isolation(system):
    settings, _, admin, user = system
    context = sample_context()
    first, _ = AI(user, settings, FakeClient).company_report(context)
    assert AI(admin, settings, FakeClient).saved_company_report(context) is None
    assert AI(user, replace(settings, deepseek_api_key=''), FakeClient).company_report(context) == (first, True)
    with pytest.raises(SetupRequired, match='AI研究服务尚未配置'):
        AI(admin, replace(settings, deepseek_api_key=''), FakeClient).company_report(context)


@pytest.mark.parametrize('failure', ['timeout', 'bad_json', 'wrong_shape', 'http_error', 'key_echo'])
def test_failure_redacted_no_repeat_no_invalid_report_and_retains_previous(system, failure, caplog, capsys):
    settings, _, _, repo = system
    context = sample_context()
    previous, _ = AI(repo, settings, FakeClient).company_report(context)
    class Failed(FakeClient):
        def post(self, url, **kwargs):
            if failure == 'timeout':raise httpx.ReadTimeout('SECRET_API_KEY header body')
            if failure == 'http_error':return httpx.Response(500, request=httpx.Request('POST', url), text='SECRET_API_KEY')
            self.text = report_text('test-not-real-key') if failure == 'key_echo' else ('not json' if failure == 'bad_json' else '{}')
            return super().post(url, **kwargs)
    with pytest.raises(UserError) as exc:
        AI(repo, settings, Failed).company_report(context, regenerate=True)
    assert 'SECRET_API_KEY' not in str(exc.value)+caplog.text+capsys.readouterr().out
    assert AI(repo, settings).saved_company_report(context) == previous
    with repo.db.connect() as conn:
        assert len(conn.execute(select(usage).where(usage.c.status == 'unknown')).all()) == 1


def test_concurrent_company_request_single_call_and_budget(system):
    settings, auth, admin, user = system
    context = sample_context()
    service = AI(user, settings, FakeClient)
    def call():
        try:return service.company_report(context)
        except UserError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results = list(pool.map(lambda _: call(), range(2)))
    assert len(FakeClient.calls) == 1 and any(results)
    changed = copy.deepcopy(context)
    changed['security']['code']['value'] = '600001'
    with pytest.raises(UserError, match='预算'):
        AI(user, replace(settings, daily_budget=Decimal('0')), FakeClient).company_report(changed)


def test_invalid_structure_is_rejected():
    report = json.loads(report_text())
    report['sections'][0]['title'] = '买卖建议'
    with pytest.raises(ValueError):parse_report(json.dumps(report))
    assert '不得虚构数字' in SYSTEM and '不得使用模型记忆' in SYSTEM
    assert request_key(sample_context(), 'deepseek-chat') != request_key(sample_context(), 'other-model')
