"""Official gov.cn response excerpts captured 2026-10-30; never live requests in tests."""
import json
from pathlib import Path

import httpx
import pytest

from alphalab.data import fetch_policy_index, read_home_sections
from alphalab.policy_parser import INDEX, parse_index
from alphalab.provider import validate
import pandas as pd

FIXTURES = Path(__file__).parent / 'fixtures' / 'gov_policy'
CATALOG = INDEX + 'ZUIXINZHENGCE.json'


def test_actual_dynamic_index_discovers_catalog_without_fabricating_records():
    rows, resources = parse_index((FIXTURES / 'index_excerpt.html').read_bytes())
    assert rows == []
    assert resources == [CATALOG]


@pytest.mark.parametrize('wrapper', ['list', 'nested', 'assignment'])
def test_actual_catalog_publication_field_in_supported_containers(wrapper):
    raw = (FIXTURES / 'catalog_excerpt.json').read_text()
    records = json.loads(raw)
    if wrapper == 'nested':raw = json.dumps({'data': {'records': records}})
    if wrapper == 'assignment':raw = '<script>var records = ' + raw + ';</script>'
    rows, _ = parse_index(raw, CATALOG)
    assert len(rows) == len(records) == 3
    for row, original in zip(rows, records):
        assert row['title'] == original['TITLE']
        assert row['url'] == original['URL']
        assert row['published_at'] == original['DOCRELPUBTIME']
    validate('government_policy_index', pd.DataFrame(rows))


@pytest.mark.parametrize('published', [None, '', '2026-02-30', 'unknown'])
def test_catalog_never_infers_missing_or_invalid_publication_date(published):
    record = json.loads((FIXTURES / 'catalog_excerpt.json').read_text())[0]
    # Both title and URL contain dates; neither can supply publication metadata.
    record['TITLE'] = '2026年10月26日政策日期回归测试'
    record['URL'] = 'https://www.gov.cn/zhengce/20261026/content_7084279.htm'
    if published is None:record.pop('DOCRELPUBTIME')
    else:record['DOCRELPUBTIME'] = published
    assert parse_index(json.dumps([record]))[0] == []


def test_catalog_field_case_and_date_format_are_not_sample_specific():
    record = {'title': '官方发布日期字段兼容测试', 'url': '/zhengce/content/example.htm',
              'docrelpubtime': '2026年10月28日'}
    assert parse_index(json.dumps({'rows': [record]}))[0][0]['published_at'] == '2026-10-28'
    record['url'] = 'https://untrusted.example/policy.htm'
    assert parse_index(json.dumps(record))[0] == []


def test_actual_page_to_catalog_fetch_with_verified_same_origin(monkeypatch):
    original = httpx.Client
    seen = []
    def handler(request):
        seen.append(str(request.url))
        assert request.url.scheme == 'https' and request.url.host == 'www.gov.cn'
        if str(request.url) == INDEX:
            return httpx.Response(200, content=(FIXTURES / 'index_excerpt.html').read_bytes())
        assert str(request.url) == CATALOG
        return httpx.Response(200, content=(FIXTURES / 'catalog_excerpt.json').read_bytes())
    def client(**kwargs):
        assert kwargs.get('verify', True) is True
        assert kwargs['follow_redirects'] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(httpx, 'Client', client)
    result = fetch_policy_index()
    assert seen == [INDEX, CATALOG]
    assert len(result['items']) == 3
    assert result['items'][0]['published_at'] == '2026-10-26'


def test_policy_failure_does_not_hide_other_home_sections():
    class Data:
        def indices(self, refresh=False):return {'items': [{'code': 'sh000001'}]}
        def policies(self, refresh=False):raise RuntimeError('policy source unavailable')
    result = read_home_sections(Data(), refresh=True)
    assert result['indices']['result']['items'] == [{'code': 'sh000001'}]
    assert isinstance(result['policies']['result'], RuntimeError)
