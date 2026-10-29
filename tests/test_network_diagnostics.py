import socket
import ssl
import httpx
import pytest
from alphalab import network_diagnostics as n, provider as p

@pytest.fixture(autouse=True)
def clear(monkeypatch):
    n._results.clear()
    for key in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy'):monkeypatch.delenv(key,raising=False)
    yield
    n._results.clear()

@pytest.mark.parametrize('status,expected',[(200,'CONNECTED'),(403,'HTTP_FORBIDDEN'),(429,'HTTP_RATE_LIMITED'),(302,'HTTP_REDIRECT')])
def test_network_stages_and_no_body_or_secrets(monkeypatch,capsys,status,expected):
    monkeypatch.setattr(n,'resolve',lambda *a,**k:[('fixture-address',)])
    monkeypatch.setattr(n,'direct_transport',lambda *a,**k:None)
    original=httpx.Client
    class UnreadBody(httpx.SyncByteStream):
        def __iter__(self):raise AssertionError('Headers-only probe must not read response body')
    def handler(request):
        assert request.url.query==b''
        return httpx.Response(status,stream=UnreadBody(),headers={'set-cookie':'secret-cookie','location':'https://secret.example/'})
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    report=n.target_report(('www.gov.cn','/zhengce/zuixin/'))
    assert report['dns']==report['tcp']==report['tls']=='CONNECTED'
    assert report['https']==expected
    assert all(report[k]>=0 for k in ('dns_seconds','tcp_seconds','tls_seconds','https_seconds'))
    assert 'secret' not in str(report)
    out=capsys.readouterr();assert not out.out+out.err


def test_dns_failure_does_not_hide_https_result_with_proxy(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://private-proxy.invalid:8000')
    def fail(*a,**k):raise socket.gaierror('secret')
    monkeypatch.setattr(n,'resolve',fail)
    monkeypatch.setattr(n,'direct_transport',lambda *a,**k:pytest.fail('Must not bypass proxy'))
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(lambda req:httpx.Response(200)),**kwargs))
    report=n.target_report(('www.gov.cn','/'))
    assert report['dns']=='DNS_ERROR' and report['tcp']==report['tls']=='PROXY_ROUTE'
    assert report['https']=='CONNECTED'


def test_stage_tls_and_timeout_classification():
    def tls():raise ssl.SSLError('private certificate details')
    def timeout():raise TimeoutError('private request details')
    assert n.measure(tls)[0]=='TLS_ERROR'
    assert n.measure(timeout)[0]=='NETWORK_TIMEOUT'


def test_group_is_bounded_cached_and_admin_only(system,monkeypatch):
    _,_,admin,user=system
    calls=[]
    monkeypatch.setattr(n,'target_report',lambda target:calls.append(target[0]) or {'host':target[0],'https':'CONNECTED'})
    from alphalab.config import UserError
    with pytest.raises(UserError):n.report_for_admin(user,'政府网')
    assert not calls
    first=n.report_for_admin(admin,'政府网');second=n.report_for_admin(admin,'政府网')
    assert first[0]['cached'] is False and second[0]['cached'] is True
    assert calls==['www.gov.cn']
    assert n.group_report('https://user-input.invalid')==[]
