"""Data integrity regressions; source-shaped fixtures are never application data."""
import json
import subprocess
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import delete

from alphalab import provider, market_diagnostics
from alphalab.data import MarketData, DataUnavailable
from alphalab.db import cache, public, today
from alphalab.policy_parser import parse_index


def test_search_never_requests_bj_but_reads_existing_bj_cache(system, monkeypatch):
    _, auth, _, _ = system
    data = MarketData(auth.db)
    calls = []
    def call(name, **kwargs):
        calls.append(name)
        if name == 'stock_info_bj_name_code':pytest.fail('Search must never wait for BJ')
        raise provider.ProviderError('NETWORK_TIMEOUT')
    monkeypatch.setattr(provider, 'call', call)
    with pytest.raises(DataUnavailable):data.search('920001')
    with pytest.raises(DataUnavailable):data.search('测试')
    assert 'stock_info_bj_name_code' not in calls
    data.cached('master:v1:BJ', 0, 'BJ fixture', lambda: {'items': [
        {'code': '920001', 'name': '测试北交所', 'exchange': 'BJ', 'total_shares': '123,456'}]}, 'stock_master')
    assert data.search('测试')[0]['code'] == '920001'
    assert data.search('920001')[0]['stale']


@pytest.mark.parametrize('public_fallback', [False, True])
def test_sz_legacy_capital_never_becomes_company_total(system, monkeypatch, public_fallback):
    _, auth, _, _ = system
    data = MarketData(auth.db)
    data.cached('master:v1:SZ', 3600, 'SZ legacy fixture', lambda: {'items': [
        {'code': '000001', 'name': '测试深市', 'exchange': 'SZ', 'total_shares': 123}]}, 'stock_master')
    if public_fallback:
        with auth.db.begin() as conn:conn.execute(delete(cache))
    monkeypatch.setattr(provider, 'call', lambda *a, **k: (_ for _ in ()).throw(provider.ProviderError('NETWORK_TIMEOUT')))
    assert 'total_shares' not in data.search('000001')[0]
    assert data.company('000001')['items'][0]['总股本'] == '暂无可靠数据'


def test_explicit_capital_only_and_bj_prefixes(system, monkeypatch):
    _, auth, _, _ = system
    def call(name, **kwargs):
        if name == 'stock_info_sz_name_code':
            return pd.DataFrame([{'A股代码': '000001', 'A股简称': '深市', 'A股总股本': 123}])
        if name == 'stock_info_bj_name_code':
            return pd.DataFrame([{'证券代码': code, '证券简称': '北市', '总股本': 456}
                                 for code in ('430001', '830001', '920001')])
        return pd.DataFrame([{'证券代码': '600001', '证券简称': '沪市'}])
    monkeypatch.setattr(provider, 'call', call)
    data = MarketData(auth.db)
    rows = data.security_master(refresh=True)['items']
    assert all('total_shares' not in row for row in rows if row['exchange'] in ('SH', 'SZ'))
    assert len([row for row in rows if row['exchange'] == 'BJ' and row['total_shares'] == 456]) == 3
    assert data.company('920001')['items'][0]['总股本'] == 456


def test_bj_timeout_has_own_budget_and_sh_sz_still_persist(system, monkeypatch):
    _, auth, _, _ = system
    budgets = {}
    def run(args, **kwargs):
        name = args[-2]
        budgets[name] = kwargs['timeout']
        if name == 'stock_info_bj_name_code':raise subprocess.TimeoutExpired('redacted', 45)
        fields = {'证券代码': '600001', '证券简称': '沪市'} if name == 'security_master_sh' else {'A股代码': '000001', 'A股简称': '深市'}
        return SimpleNamespace(returncode=0, stdout=pd.DataFrame([fields]).to_json(orient='split'))
    monkeypatch.setattr(provider.subprocess, 'run', run)
    provider._failures.clear()
    try:
        rows = MarketData(auth.db).security_master(refresh=True)['items']
        assert {row['exchange'] for row in rows} == {'SH', 'SZ'}
        assert budgets == {'security_master_sh': 12, 'stock_info_sz_name_code': 12, 'stock_info_bj_name_code': 45}
        assert provider._failures[('stock_info_bj_name_code', '{}')][1] == 'PROVIDER_TIMEOUT'
    finally:provider._failures.clear()


def test_sina_financial_adapter_to_current_metrics():
    entries = [
        ('营业总收入（元）', '1,234,567.89'), ('归属于母公司股东的净利润（元）', '-12,345'),
        ('净资产收益率（加权）（%）', '12.5'), ('销售毛利率（%）', '31.2'),
        ('资产负债率（%）', '40'), ('经营活动产生的现金流量净额（元）', '9,876'),
        ('每股经营活动产生的现金流量净额（元）', '2'), ('营业收入增长率（%）', '3')]
    response = SimpleNamespace(json=lambda: {'result': {'data': {'report_list': {
        '20260930': {'data': [{'item_title': title, 'item_value': value} for title, value in entries]}}}}})
    requests = SimpleNamespace(get=lambda *a, **k: response)
    frame = provider.financial_frame(requests, '600001')
    data = {'items': frame.to_dict('records')}
    summary = MarketData.financial_summary(data)
    assert {name: row['value'] for name, row in summary.items()} == {
        '营业收入': 1234567.89, '净利润': -12345, 'ROE': 12.5, '毛利率': 31.2,
        '资产负债率': 40, '经营现金流': 9876}
    assert MarketData.quality_metrics(data) == {'roe': 12.5, 'profit': -12345}
    missing = MarketData.financial_summary({'items': [
        {'指标': '营业收入增长率（%）', '20260930': 5},
        {'指标': '每股经营活动产生的现金流量净额（元）', '20260930': 2},
        {'指标': '营业收入（万元）', '20260930': 20}]})
    assert all(row['value'] is None for row in missing.values())


def test_indices_partial_failure_retains_other_indices_and_old_cache(system, monkeypatch):
    from datetime import timedelta
    _, auth, _, _ = system
    data = MarketData(auth.db)
    data.cached('index:sina:sz399001', 1, 'Sina fixture', lambda: {'items': [
        {'code': 'sz399001', 'name': '深证成指', 'price': 100, 'date': '2026-10-01'}]})
    def call(name, **kwargs):
        assert name == 'stock_zh_index_daily'
        if kwargs['symbol'] != 'sh000001':raise provider.ProviderError('NETWORK_TIMEOUT')
        return pd.DataFrame([{'date': str(today()-timedelta(days=2)), 'close': 100},
                             {'date': str(today()-timedelta(days=1)), 'close': 101}])
    monkeypatch.setattr(provider, 'call', call)
    result = data.indices(refresh=True)
    rows = {row['code']: row for row in result['items']}
    assert set(rows) == {'sh000001', 'sz399001'}
    assert not rows['sh000001']['stale'] and rows['sz399001']['stale']
    assert result['diagnostics'] == {'sz399001': 'NETWORK_TIMEOUT', 'sz399006': 'NETWORK_TIMEOUT'}


def test_three_indices_have_separate_diagnostics(monkeypatch):
    market_diagnostics._results.clear()
    calls = []
    def call(name, **kwargs):
        calls.append((name, kwargs['symbol']))
        if kwargs['symbol'] == 'sz399001':raise provider.ProviderError('NETWORK_TIMEOUT')
    monkeypatch.setattr(provider, 'call', call)
    try:
        assert market_diagnostics.probe('stock_zh_index_daily') == 'CONNECTED'
        assert market_diagnostics.probe('sina_index_sz399001') == 'NETWORK_TIMEOUT'
        assert market_diagnostics.probe('sina_index_sz399006') == 'CONNECTED'
        assert calls == [('stock_zh_index_daily', code) for code in ('sh000001', 'sz399001', 'sz399006')]
    finally:market_diagnostics._results.clear()


@pytest.mark.parametrize('record', [
    {'publishDate': '2026年10月28日'}, {'pub_date': '2026/10/28'}, {'发布日期': '2026.10.28'},
])
def test_policy_explicit_date_fields(record):
    record.update(title='政策日期解析测试', url='/zhengce/content/a.htm')
    assert parse_index(json.dumps(record))[0][0]['published_at'] == '2026-10-28'


def test_policy_dates_are_not_inferred_from_headlines_or_shared_containers():
    assert not parse_index('<li><a href="/zhengce/a.htm">2026年10月28日会议政策标题</a></li>')[0]
    assert not parse_index('<li><span>2026-10-28 / 2026-10-29</span><a href="/zhengce/a.htm">日期歧义政策标题</a></li>')[0]
    rows, _ = parse_index('<li data-pubdate="2026-10-28"><a href="/zhengce/a.htm">政策日期解析测试</a></li>')
    assert rows[0]['published_at'] == '2026-10-28'
