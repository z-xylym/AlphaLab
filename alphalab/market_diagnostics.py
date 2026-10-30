"""Administrator-only read-only probes from the actual app's network location."""
import time
from threading import RLock
from . import provider

PROBES = {
    'security_master_sh': {}, 'stock_info_sz_name_code': {}, 'stock_info_bj_name_code': {},
    'stock_zh_index_daily': {'symbol':'sh000001'},
    'sina_index_sz399001': {'symbol':'sz399001'},
    'sina_index_sz399006': {'symbol':'sz399006'},
    'government_policy_index': {},
    'stock_zh_a_spot_em': {}, 'stock_zh_a_spot': {},
    'stock_zh_index_daily_em': {'symbol':'sh000001'},
    'stock_board_industry_name_em': {}, 'stock_board_concept_name_em': {},
    'stock_zh_a_hist': {'symbol':'600868','start_date':'20260101','end_date':'20261029','adjust':''},
    'stock_zh_a_daily': {'symbol':'sh600868','start_date':'20260101','end_date':'20261029','adjust':''},
    'stock_individual_info_em': {'symbol':'600868'},
    'stock_zygc_em': {'symbol':'SH600868'},
    'sina_financial_summary': {'symbol':'600868'},
}
_results={}
_lock=RLock()

def probe(endpoint):
    if endpoint not in PROBES:return 'OTHER_ERROR'
    # Serialize probes per process and cache categories for 30s; no mass probe button.
    with _lock:
        previous=_results.get(endpoint)
        if previous and time.monotonic()-previous[0]<30:return previous[1]
        kwargs=dict(PROBES[endpoint])
        if endpoint in ('stock_zh_a_hist','stock_zh_a_daily'):
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo
            end=datetime.now(ZoneInfo('Asia/Shanghai')).date()
            kwargs.update(start_date=(end-timedelta(days=90)).strftime('%Y%m%d'),end_date=end.strftime('%Y%m%d'))
        try:
            started=time.monotonic()
            provider.call('stock_zh_index_daily' if endpoint.startswith('sina_index_') else endpoint,_diagnostic=True,**kwargs)
            category='CONNECTED'
        except Exception as exc:category=provider.classify(exc)
        _results[endpoint]=(time.monotonic(),category,round(time.monotonic()-started,3))
        return category

def probe_for_admin(repo,endpoint):
    # Do not rely on hiding the UI: validate current server session and role again.
    with repo.db.begin() as conn:
        repo.auth.principal(conn,repo.token,admin=True)
    return probe(endpoint)


def probe_report_for_admin(repo,endpoint):
    with repo.db.begin() as conn:
        repo.auth.principal(conn,repo.token,admin=True)
    prior=_results.get(endpoint)
    cached=bool(prior and time.monotonic()-prior[0]<30)
    category=probe(endpoint)
    record=_results.get(endpoint)
    return {'endpoint':endpoint,'category':category,'elapsed_seconds':record[2] if record else 0,'cached':cached}
