"""Bounded, TLS-verified public data calls; child errors use an allowlisted protocol."""
import contextlib
import io
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from threading import RLock
import pandas as pd

REQUEST_TIMEOUT = (3, 5)  # connect / read inactivity; total call is independently bounded.
PROVIDER_TIMEOUT = 12
FAILURE_COOLDOWN = 60
CATEGORIES = frozenset({'CONNECTED','DNS_ERROR','NETWORK_TIMEOUT','NETWORK_ERROR','HTTP_FORBIDDEN',
    'HTTP_RATE_LIMITED','HTTP_ERROR','TLS_ERROR','PROVIDER_SCHEMA_CHANGED','AKSHARE_VERSION_INCOMPATIBLE',
    'AKSHARE_CALL_FAILED','OTHER_ERROR','PROVIDER_TIMEOUT','HTTP_REDIRECT'})
REQUIRED = {
    'government_policy_index': {'title','url','published_at'},
    'stock_zh_a_spot_em': {'代码','名称','最新价'}, 'stock_zh_a_spot': {'代码','名称','最新价'},
    'stock_zh_index_daily_em': {'date','close'}, 'stock_board_industry_name_em': {'板块名称','板块代码'},
    'stock_board_concept_name_em': {'板块名称','板块代码'}, 'stock_zh_a_hist': {'日期','开盘','最高','最低','收盘','成交量'},
    'stock_zh_a_daily': {'date','open','high','low','close','volume'}, 'stock_individual_info_em': {'item','value'},
    'stock_zygc_em': {'报告日期','主营构成'}, 'stock_financial_abstract': {'指标'},
    'sina_financial_summary': {'指标'}, 'stock_board_industry_cons_em': {'代码','名称','最新价'},
    'stock_board_concept_cons_em': {'代码','名称','最新价'},
}
_failures = {}
_lock = RLock()

class ProviderError(Exception):
    def __init__(self, category):
        self.category = category if category in CATEGORIES and category != 'CONNECTED' else 'OTHER_ERROR'
        super().__init__(self.category)

def classify(exc):
    if isinstance(exc, ProviderError): return exc.category
    if isinstance(exc, subprocess.TimeoutExpired): return 'PROVIDER_TIMEOUT'
    messages=[]; seen=set(); pending=[exc]
    while pending and len(seen)<12:
        value=pending.pop()
        if id(value) in seen: continue
        seen.add(id(value))
        status=getattr(getattr(value,'response',None),'status_code',None)
        if status==403:return 'HTTP_FORBIDDEN'
        if status==429:return 'HTTP_RATE_LIMITED'
        if status is not None and status>=400:return 'HTTP_ERROR'
        if isinstance(value,(ssl.SSLError,)):return 'TLS_ERROR'
        if isinstance(value,socket.gaierror):return 'DNS_ERROR'
        messages.append(str(value).lower())  # INTERNAL ONLY; never returned or printed.
        for child in (getattr(value,'__cause__',None),getattr(value,'__context__',None)):
            if isinstance(child,BaseException):pending.append(child)
    message=' '.join(messages)
    if any(x in message for x in ('certificate verify failed','sslerror','ssl:','tls')):return 'TLS_ERROR'
    if any(x in message for x in ('name resolution','name or service not known','failed to resolve','getaddrinfo')):return 'DNS_ERROR'
    if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)) or 'timeout' in type(exc).__name__.lower() or 'timed out' in message:return 'NETWORK_TIMEOUT'
    if isinstance(exc,(KeyError,ValueError,IndexError)):return 'PROVIDER_SCHEMA_CHANGED'
    if isinstance(exc,AttributeError):return 'AKSHARE_VERSION_INCOMPATIBLE'
    if 'proxy' in type(exc).__name__.lower() or 'connection' in type(exc).__name__.lower() or any(x in message for x in ('unreachable','connection refused','connection reset')):return 'NETWORK_ERROR'
    return 'AKSHARE_CALL_FAILED'

def validate(name, frame):
    if name not in REQUIRED:raise ProviderError('AKSHARE_VERSION_INCOMPATIBLE')
    if frame.empty or not REQUIRED[name].issubset(frame.columns):raise ProviderError('PROVIDER_SCHEMA_CHANGED')
    return frame

def call(name, _diagnostic=False, **kwargs):
    if name not in REQUIRED:raise ProviderError('AKSHARE_VERSION_INCOMPATIBLE')
    key=(name,json.dumps(kwargs,sort_keys=True))
    with _lock:
        prior=_failures.get(key)
        if not _diagnostic and prior and time.monotonic()-prior[0]<FAILURE_COOLDOWN:
            raise ProviderError(prior[1])
    try:
        child_env=os.environ.copy()
        for variable in ('DATABASE_URL','APP_SECRET_KEY','DEEPSEEK_API_KEY','SUPABASE_CA_CERT','ADMIN_PHONE','ADMIN_INITIAL_PASSWORD'):
            child_env.pop(variable,None)
        result=subprocess.run([sys.executable,'-m','alphalab.provider',name,json.dumps(kwargs)],
            capture_output=True,text=True,timeout=PROVIDER_TIMEOUT,check=False,env=child_env)
        if getattr(result,'returncode',0):
            try:category=json.loads(getattr(result,'stderr',''))['category']
            except Exception:category='AKSHARE_CALL_FAILED'
            raise ProviderError(category)
        try:frame=pd.read_json(io.StringIO(result.stdout),orient='split',dtype=False)
        except Exception:raise ProviderError('PROVIDER_SCHEMA_CHANGED') from None
        frame=validate(name,frame)
    except Exception as exc:
        category=classify(exc)
        with _lock:
            if len(_failures)>=128:_failures.pop(next(iter(_failures)))
            _failures[key]=(time.monotonic(),category)
        raise ProviderError(category) from None
    with _lock:_failures.pop(key,None)
    return frame

def install_transport(requests):
    from urllib.parse import urlparse
    original=requests.Session.request
    state={'category':None}
    def verified_request(self,method,url,**kwargs):
        try:
            if url.startswith('http://'):
                host=urlparse(url).hostname or ''
                if host.endswith('.sina.com.cn') or host.endswith('.eastmoney.com'):url='https://'+url[7:]
                else:raise ProviderError('TLS_ERROR')
            if kwargs.get('verify') is False:raise ProviderError('TLS_ERROR')
            # AKShare sometimes explicitly passes timeout=None; setdefault did not bound it.
            kwargs['timeout']=REQUEST_TIMEOUT
            response=original(self,method,url,**kwargs)
            response.raise_for_status()  # Record 403/429 BEFORE a JSON parse hides the cause.
            return response
        except Exception as exc:
            state['category']=classify(exc)
            raise ProviderError(state['category']) from None
    requests.Session.request=verified_request
    return state

def financial_frame(requests, code):
    symbol=('sh' if code.startswith('6') else 'sz' if code.startswith(('0','3')) else 'bj')+code
    response=requests.get('https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022',
        params={'paperCode':symbol,'source':'gjzb','type':'0','page':'1','num':'8'})
    reports=response.json()['result']['data']['report_list'];metrics={}
    for period, report in reports.items():
        for item in report['data']:
            value=pd.to_numeric(item.get('item_value'),errors='coerce')
            if pd.notna(value):metrics.setdefault(item['item_title'],{'指标':item['item_title']})[period]=float(value)
    return pd.DataFrame(metrics.values())

def worker(name, kwargs):
    state={'category':None}
    try:
        if name not in REQUIRED:raise ProviderError('AKSHARE_VERSION_INCOMPATIBLE')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import requests
            state=install_transport(requests)
            import akshare
            if name=='government_policy_index':
                from .data import fetch_policy_index
                frame=pd.DataFrame(fetch_policy_index()['items'])
            elif name=='sina_financial_summary':frame=financial_frame(requests,kwargs['symbol'])
            else:frame=getattr(akshare,name)(**kwargs)
            validate(name,frame)
        print(frame.to_json(orient='split',force_ascii=False,date_format='iso'))
        return 0
    except Exception as exc:
        category=state['category'] or classify(exc)
        # Only this safe envelope crosses the process boundary, never raw stderr.
        print(json.dumps({'category':category}),file=sys.stderr)
        return 1

if __name__=='__main__':
    try:status=worker(sys.argv[1],json.loads(sys.argv[2]))
    except Exception:
        print(json.dumps({'category':'OTHER_ERROR'}),file=sys.stderr);status=1
    raise SystemExit(status)
