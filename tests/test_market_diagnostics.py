import json
import socket
import ssl
import subprocess
from types import SimpleNamespace
import httpx
import pandas as pd
import pytest
from alphalab import provider as p, market_diagnostics as m

@pytest.fixture(autouse=True)
def clear():
    p._failures.clear();m._results.clear()
    yield
    p._failures.clear();m._results.clear()

@pytest.mark.parametrize('error,expected',[
    (socket.gaierror('secret-host'),'DNS_ERROR'),(TimeoutError('secret-url'),'NETWORK_TIMEOUT'),
    (ssl.SSLError('secret'),'TLS_ERROR'),(ConnectionError('secret'),'NETWORK_ERROR'),
    (KeyError('secret-body'),'PROVIDER_SCHEMA_CHANGED'),(AttributeError('secret'),'AKSHARE_VERSION_INCOMPATIBLE'),
    (RuntimeError('secret'),'AKSHARE_CALL_FAILED'),
])
def test_classification_is_fixed(error,expected):
    assert p.classify(error)==expected

@pytest.mark.parametrize('status,expected',[(403,'HTTP_FORBIDDEN'),(429,'HTTP_RATE_LIMITED'),(500,'HTTP_ERROR')])
def test_status_not_hidden_by_json_parse(status,expected):
    error=httpx.HTTPStatusError('secret',request=httpx.Request('GET','https://example.org/?secret=private'),response=httpx.Response(status))
    assert p.classify(error)==expected


def test_transport_replaces_none_timeout_and_checks_status(monkeypatch):
    import requests
    observed={}
    def request(self,method,url,**kwargs):
        observed.update(kwargs)
        response=requests.Response();response.status_code=403;response.url='https://example.org/private'
        return response
    monkeypatch.setattr(requests.Session,'request',request)
    state=p.install_transport(requests)
    with pytest.raises(p.ProviderError,match='HTTP_FORBIDDEN'):requests.get('https://example.org/',timeout=None)
    assert observed['timeout']==(3,5) and state['category']=='HTTP_FORBIDDEN'


def test_no_tls_bypass(monkeypatch):
    import requests
    def forbidden(*a,**k):pytest.fail('TLS bypass must never reach transport')
    monkeypatch.setattr(requests.Session,'request',forbidden)
    p.install_transport(requests)
    with pytest.raises(p.ProviderError):requests.get('https://example.org',verify=False)


def test_failure_cooldown_and_diagnostic_bypass(monkeypatch):
    seen=[]
    def run(*args,**kwargs):
        seen.append(1)
        assert kwargs['timeout']==12
        assert 'DATABASE_URL' not in kwargs['env']
        return SimpleNamespace(returncode=1,stderr=json.dumps({'category':'HTTP_RATE_LIMITED'}))
    monkeypatch.setenv('DATABASE_URL','secret')
    monkeypatch.setattr(p.subprocess,'run',run)
    for _ in range(2):
        with pytest.raises(p.ProviderError,match='HTTP_RATE_LIMITED'):p.call('stock_board_industry_name_em')
    assert len(seen)==1
    with pytest.raises(p.ProviderError):p.call('stock_board_industry_name_em',_diagnostic=True)
    assert len(seen)==2


def test_timeout_and_untrusted_child_output_are_redacted(monkeypatch,capsys):
    def timeout(*a,**k):raise subprocess.TimeoutExpired('private-url',12,output='secret-body')
    monkeypatch.setattr(p.subprocess,'run',timeout)
    with pytest.raises(p.ProviderError) as caught:p.call('stock_zh_a_spot_em')
    assert str(caught.value)=='PROVIDER_TIMEOUT'
    p._failures.clear()
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stderr='private-headers cookies secret'))
    with pytest.raises(p.ProviderError) as caught:p.call('stock_zh_a_spot_em')
    assert str(caught.value)=='AKSHARE_CALL_FAILED'
    out=capsys.readouterr();assert not out.out+out.err


def test_schema_is_checked_before_fallback(monkeypatch):
    from alphalab.data import MarketData
    calls=[]
    def run(args,**kwargs):
        name=args[3];calls.append(name)
        frame=pd.DataFrame([{'unexpected':'secret-body'}]) if name.endswith('_em') else pd.DataFrame([{'代码':'sh600868','名称':'测试夹具','最新价':10}])
        return SimpleNamespace(returncode=0,stdout=frame.to_json(orient='split'))
    monkeypatch.setattr(p.subprocess,'run',run)
    data=MarketData(None)
    monkeypatch.setattr(data,'cached',lambda key,ttl,source,loader,storage=None:loader())
    assert data.spot()['items'][0]['code']=='600868'
    assert calls==['stock_zh_a_spot_em','stock_zh_a_spot']


def test_admin_role_checked_before_network(system,monkeypatch):
    _,_,admin,user=system
    seen=[]
    monkeypatch.setattr(m,'probe',lambda endpoint:seen.append(endpoint) or 'CONNECTED')
    from alphalab.config import UserError
    with pytest.raises(UserError):m.probe_for_admin(user,'stock_zh_a_spot_em')
    assert not seen
    assert m.probe_for_admin(admin,'stock_zh_a_spot_em')=='CONNECTED'


def test_probe_is_single_endpoint_read_only_and_cooldown(monkeypatch):
    seen=[]
    def run(name,**kwargs):seen.append(name);raise p.ProviderError('HTTP_FORBIDDEN')
    monkeypatch.setattr(p,'call',run)
    assert m.probe('stock_board_concept_name_em')=='HTTP_FORBIDDEN'
    assert m.probe('stock_board_concept_name_em')=='HTTP_FORBIDDEN'
    assert seen==['stock_board_concept_name_em']
    assert m.probe('unknown')=='OTHER_ERROR'


def test_home_reads_independent_sources_concurrently():
    from threading import Barrier
    from alphalab.data import read_home_sections, DataUnavailable
    barrier=Barrier(3,timeout=3)
    class Data:
        def indices(self):barrier.wait();return {'items':[{'fixture':True}]}
        def spot(self):barrier.wait();raise DataUnavailable('测试源不可用')
        def policies(self):barrier.wait();return {'items':[]}
    result=read_home_sections(Data())
    assert result['indices']['result']['items'][0]['fixture']
    assert isinstance(result['spot']['result'],DataUnavailable)
    assert all(row['elapsed_seconds']>=0 for row in result.values())

@pytest.mark.parametrize('category',['CONNECTED','secret-response-body'])
def test_failed_child_cannot_report_connected_or_untrusted_category(monkeypatch,category):
    monkeypatch.setattr(p.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stderr=json.dumps({'category':category})))
    with pytest.raises(p.ProviderError,match='OTHER_ERROR'):p.call('stock_zh_a_spot_em')


def test_child_rejects_non_allowlisted_method_before_import(capsys):
    assert p.worker('not-an-approved-endpoint',{})==1
    output=capsys.readouterr()
    assert not output.out
    assert json.loads(output.err)=={'category':'AKSHARE_VERSION_INCOMPATIBLE'}
