"""Fixed public targets only; staged results contain no URLs/headers/body/credentials."""
from concurrent.futures import ThreadPoolExecutor
import os
import socket
import ssl
import time
from threading import RLock
import httpx
from .provider import classify, ProviderError
from .db_diagnostics import resolve

GROUPS={
    '政府网': [('www.gov.cn','/zhengce/zuixin/')],
    '东方财富': [(host,path) for host,path in (
        ('17.push2.eastmoney.com','/api/qt/clist/get'),('79.push2.eastmoney.com','/api/qt/clist/get'),
        ('82.push2.eastmoney.com','/api/qt/clist/get'),('push2his.eastmoney.com','/api/qt/stock/kline/get'),
        ('push2.eastmoney.com','/api/qt/stock/get'),('emweb.securities.eastmoney.com','/PC_HSF10/BusinessAnalysis/PageAjax'))],
    '新浪': [('vip.stock.finance.sina.com.cn','/'),('finance.sina.com.cn','/'),('quotes.sina.cn','/')],
}
_results={};_lock=RLock()

def measure(action):
    start=time.monotonic()
    try:
        action();category='CONNECTED'
    except Exception as exc:category=classify(exc)
    return category,round(time.monotonic()-start,3)

def direct_transport(addresses,host,tls=False):
    deadline=time.monotonic()+3
    error=TimeoutError()
    context=httpx.create_ssl_context(trust_env=True) if tls else None
    for family,kind,proto,_,address in addresses:
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        try:
            with socket.socket(family,kind,proto) as conn:
                conn.settimeout(remaining);conn.connect(address)
                if tls:
                    with context.wrap_socket(conn,server_hostname=host):pass
            return
        except Exception as exc:error=exc
    raise error

def target_report(target):
    host,path=target
    started=time.monotonic()
    report={'host':host}
    addresses=[]
    def dns():addresses.extend(resolve(host,443,timeout=3))
    report['dns'],report['dns_seconds']=measure(dns)
    # Honor inherited proxy routing. A direct failure must not be called a proxy failure.
    proxy=any(os.environ.get(key) for key in ('HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy'))
    if proxy:
        report.update(tcp='PROXY_ROUTE',tls='PROXY_ROUTE',tcp_seconds=0,tls_seconds=0)
    elif addresses:
        report['tcp'],report['tcp_seconds']=measure(lambda:direct_transport(addresses,host))
        report['tls'],report['tls_seconds']=measure(lambda:direct_transport(addresses,host,tls=True))
    else:
        report.update(tcp='NOT_RUN',tls='NOT_RUN',tcp_seconds=0,tls_seconds=0)
    def https():
        # Stream headers only; never download, parse or print a response body here.
        with httpx.Client(timeout=httpx.Timeout(5,connect=3),follow_redirects=False,trust_env=True) as client:
            with client.stream('GET','https://'+host+path) as response:
                if 300<=response.status_code<400:raise ProviderError('HTTP_REDIRECT')
                response.raise_for_status()
    report['https'],report['https_seconds']=measure(https)
    report['total_seconds']=round(time.monotonic()-started,3)
    return report

def group_report(group):
    if group not in GROUPS:return []
    with _lock:
        prior=_results.get(group)
        if prior and time.monotonic()-prior[0]<60:
            return [dict(row,cached=True) for row in prior[1]]
        with ThreadPoolExecutor(max_workers=3) as executor:
            rows=list(executor.map(target_report,GROUPS[group]))
        _results[group]=(time.monotonic(),rows)
        return [dict(row,cached=False) for row in rows]

def report_for_admin(repo,group):
    with repo.db.begin() as conn:
        repo.auth.principal(conn,repo.token,admin=True)
    return group_report(group)
