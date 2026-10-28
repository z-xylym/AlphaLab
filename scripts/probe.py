"""Non-destructive live checks. Outputs only status/counts; no values or fake data."""
from concurrent.futures import ThreadPoolExecutor
import httpx
from alphalab.provider import call

def probe(name):
    try:
        if name=='policy':
            r=httpx.get('https://www.gov.cn/zhengce/zuixin/',timeout=20,follow_redirects=False)
            r.raise_for_status()
            return name,'HTTP '+str(r.status_code)
        endpoint,args={
            'index':('stock_zh_index_daily_em',{'symbol':'sh000001'}),
            'company':('stock_individual_info_em',{'symbol':'600868'}),
            'sector':('stock_board_industry_name_em',{}),
        }[name]
        df=call(endpoint,**args)
        return name,'PASS rows='+str(len(df)) if len(df) else 'FAIL empty result'
    except Exception as exc:
        return name,'UNAVAILABLE '+type(exc).__name__+' (check allowed domains/provider access)'
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as p:
        for name,result in p.map(probe,['index','company','sector','policy']):print(name+': '+result)
