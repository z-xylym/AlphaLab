"""Real public data only. Failure returns a dated persisted cache or an explicit error."""
import json
import math
import re
from datetime import timedelta
from urllib.parse import urljoin, urlparse
import pandas as pd
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from .db import cache, public, now, lock, today
from .config import UserError

class DataUnavailable(UserError):
    pass

def clean(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))

def records(frame):
    return json.loads(frame.to_json(orient='records', force_ascii=False, date_format='iso'))

def number(value):
    try:
        v = float(str(value).replace(',', ''))
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None

def financial_label(value):
    # Normalize presentation only; do not conflate per-share, growth or adjusted metrics.
    label=str(value).translate(str.maketrans({'（':'(', '）':')', '％':'%'}))
    label=re.sub(r'\s+', '', label)
    return re.sub(r'\((?:%|元)\)$', '', label)


def fetch_policy_index():
    from .policy_parser import INDEX, parse_index, official
    items=[]
    with httpx.Client(timeout=httpx.Timeout(5,connect=3),follow_redirects=False) as client:
        def read(url):
            with client.stream('GET',url) as response:
                # Handle redirects only when the new resource remains the exact official origin.
                if 300<=response.status_code<400:
                    target=official(response.headers.get('location',''),url)
                    if not target or target==url:raise DataUnavailable('官方索引跳转不可验证。')
                    with client.stream('GET',target) as redirected:
                        redirected.raise_for_status()
                        return bounded(redirected)
                response.raise_for_status()
                return bounded(response)
        def bounded(response):
            chunks=[];size=0
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>2_000_000:raise DataUnavailable('官方索引格式暂不可用。')
                chunks.append(chunk)
            return b''.join(chunks)
        items,resources=parse_index(read(INDEX))
        for resource in resources if not items else []:
            try:
                extra,_=parse_index(read(resource),resource);items.extend(extra)
            except Exception:continue
    unique={row['url']:row for row in items}
    return {'items':sorted(unique.values(),key=lambda x:x['published_at'],reverse=True)[:20],
            'date_note':'官方政策索引；发布日期来自索引记录，不从链接日期猜测；具体措施须核对全文。'}

class MarketData:
    def __init__(self, db):
        self.db = db
    def cached(self, key, ttl, source, loader, storage=None, refresh=False):
        # Cross-process single-flight: the lock is held until provider result is persisted.
        with self.db.begin() as c:
            row = c.execute(select(cache).where(cache.c.key == key)).mappings().first()
            if row and not refresh:
                return {**row['payload'], 'fetched_at': row['fetched_at'].isoformat(), 'stale': row['expires_at'] <= now(), 'source': row['source']}
            lock(c, 'data:' + key)
            row = c.execute(select(cache).where(cache.c.key == key)).mappings().first()
            if row and row['expires_at'] > now() and not refresh:
                return {**row['payload'], 'fetched_at': row['fetched_at'].isoformat(), 'stale': False, 'source': row['source']}
            try:
                payload = clean(loader())
                if not payload.get('items'):
                    raise DataUnavailable('数据源未返回有效记录。')
            except Exception:
                if row:
                    return {**row['payload'], 'fetched_at': row['fetched_at'].isoformat(), 'stale': True, 'source': row['source']}
                raise DataUnavailable('数据源暂不可用，且没有历史缓存；未生成替代数据。失败请求会短暂冷却，请约一分钟后再试；管理员可在管理后台诊断。') from None
            fetched = now()
            stmt = insert(cache).values(key=key, payload=payload, source=source, fetched_at=fetched, expires_at=fetched + timedelta(seconds=ttl))
            c.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={
                'payload': payload, 'source': source, 'fetched_at': fetched, 'expires_at': fetched + timedelta(seconds=ttl)}))
            if storage:
                t = public[storage]
                batch=[]
                for i,item in enumerate(payload['items']):
                    itemkey=str(item.get('code',item.get('name',item.get('url',i))))
                    if len(itemkey)>180:
                        import hashlib
                        itemkey=hashlib.sha256(itemkey.encode()).hexdigest()
                    batch.append({'key':itemkey,'payload':item,'source':source,'fetched_at':fetched})
                batch=list({r['key']:r for r in batch}.values())
                for start in range(0,len(batch),500):
                    stmt=insert(t).values(batch[start:start+500])
                    c.execute(stmt.on_conflict_do_update(index_elements=['key'],set_={
                        'payload':stmt.excluded.payload,'source':stmt.excluded.source,'fetched_at':stmt.excluded.fetched_at}))
            return {**payload, 'fetched_at': fetched.isoformat(), 'stale': False, 'source': source}
    def cache_only(self,key,force_stale=False):
        with self.db.connect() as c:
            row=c.execute(select(cache).where(cache.c.key==key)).mappings().first()
        if not row:raise DataUnavailable('此数据源已暂停自动请求，暂无可靠缓存。')
        return {**row['payload'],'source':row['source'],'fetched_at':row['fetched_at'].isoformat(),'stale':force_stale or row['expires_at'] <= now()}
    def spot(self):
        # Both snapshot feeds have failed production checks. Do not auto retry them.
        return self.cache_only('spot:v1',force_stale=True)
    def indices(self,refresh=False):
        diagnostics={}
        def load_one(pair):
            code,name=pair
            def load():
                from .provider import call
                try:df=call('stock_zh_index_daily',symbol=code)
                except Exception as exc:
                    from .provider import classify
                    diagnostics[code]=classify(exc)
                    raise
                df['date']=pd.to_datetime(df['date'],errors='coerce')
                df=df[df['date'].notna() & (df['date'].dt.date<=today())].sort_values('date').tail(2)
                if len(df)<2:raise DataUnavailable('日线不足。')
                previous,last=df.iloc[-2],df.iloc[-1]
                if number(previous['close']) is None or number(last['close']) is None or float(previous['close'])<=0 or float(last['close'])<=0:raise DataUnavailable('日线无效。')
                return {'items':[{'code':code,'name':name,'price':number(last['close']),
                    'change_pct':(float(last['close'])/float(previous['close'])-1)*100,
                    'date':pd.to_datetime(last['date']).strftime('%Y-%m-%d')}]}
            key='index:sina:'+code
            try:
                return self.cached(key,3600,'新浪指数日线（AKShare）',load,refresh=True) if refresh else self.cache_only(key)
            except DataUnavailable:
                diagnostics.setdefault(code,'NO_RELIABLE_CACHE')
                return None
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            results=list(executor.map(load_one,[('sh000001','上证指数'),('sz399001','深证成指'),('sz399006','创业板指')]))
        available=[r for r in results if r]
        if not available:raise DataUnavailable('指数日线暂无缓存；可手动尝试新浪日线，不自动等待已失败的东方财富。')
        return {'items':[dict(x,source=r['source'],fetched_at=r['fetched_at'],stale=r['stale']) for r in available for x in r['items']],
                'source':'新浪指数日线（AKShare）','fetched_at':min(r['fetched_at'] for r in available),
                'diagnostics':diagnostics,'stale':any(r['stale'] for r in available),'date_note':'最近已发布日线，非实时；缺失指数不补值。'}
    def security_master(self,exchange=None,refresh=False,cached_only=False):
        if cached_only and refresh:
            raise ValueError('Cached-only reads cannot refresh.')
        exchanges=([exchange] if isinstance(exchange,str) else list(exchange)) if exchange else ['SH','SZ','BJ']
        if any(ex not in ('SH','SZ','BJ') for ex in exchanges):raise ValueError('Unknown exchange.')
        methods={'SH':'security_master_sh','SZ':'stock_info_sz_name_code','BJ':'stock_info_bj_name_code'}
        def one(ex):
            def safe_item(x, **metadata):
                item=dict(x, **metadata)
                # Old v1 caches persisted A-share capital under this incorrect name.
                if ex=='SZ':item.pop('total_shares',None)
                return item
            def load():
                from .provider import call
                df=call(methods[ex])
                df=df.rename(columns={'证券代码':'code','证券简称':'name','A股代码':'code','A股简称':'name',
                    'A股上市日期':'listing_date','上市日期':'listing_date','所属行业':'industry','总股本':'total_shares'})
                df['code']=df['code'].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
                df=df[df['code'].str.fullmatch(r'\d{6}') & df['name'].notna()].copy()
                prefix={'SH':('6',),'SZ':('0','3'),'BJ':('4','8','9')}[ex]
                df=df[df['code'].str.startswith(prefix)].copy()
                df['name']=df['name'].astype(str).str.strip()
                df=df[df['name'].str.len()>0]
                if ex=='SZ':df=df.drop(columns=['total_shares'],errors='ignore')
                df['exchange']=ex
                df['price']=None  # Master data must never masquerade as a price snapshot.
                items=records(df[[k for k in ('code','name','exchange','listing_date','industry','total_shares','price') if k in df.columns]])
                return {'items':items,'date_note':'交易所基础证券名单，不含实时价格；仅包含本次成功返回的交易所。'}
            try:
                data=(self.cache_only('master:v1:'+ex) if cached_only or (ex=='BJ' and not refresh) else
                      self.cached('master:v1:'+ex,86400,'交易所公开证券列表（AKShare）:'+ex,load,'stock_master',refresh=refresh))
                return [safe_item(x,source=data['source'],fetched_at=data['fetched_at'],stale=data['stale'],price=None) for x in data['items']]
            except DataUnavailable:
                with self.db.connect() as c:
                    rows=c.execute(select(public['stock_master'])).mappings().all()
                items=[]
                for r in rows:
                    x=r['payload'];code=str(x.get('code',''))
                    inferred='SH' if code.startswith('6') else 'SZ' if code.startswith(('0','3')) else 'BJ' if code.startswith(('4','8','9')) else None
                    if re.fullmatch(r'\d{6}',code) and x.get('name') and inferred==ex:
                        items.append(safe_item(x,exchange=ex,price=None,source=r['source'],fetched_at=r['fetched_at'].isoformat(),stale=True))
                return items
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:rows=[x for group in executor.map(one,exchanges) for x in group]
        if not rows:raise DataUnavailable('基础证券名单暂不可用，且无已保存真实名单；不依赖实时快照，不生成股票代码。请管理员诊断交易所名单接口。')
        return {'items':rows,'source':'逐条来源见证券记录','fetched_at':min(x['fetched_at'] for x in rows),
                'stale':any(x['stale'] for x in rows),'date_note':'基础名单与价格分离；未成功返回的交易所不保证覆盖。'}
    def search(self,query):
        q=query.strip().lower()
        if not q:return []
        ex=('SH' if q.startswith('6') else 'SZ' if q.startswith(('0','3')) else 'BJ') if re.fullmatch(r'\d{6}',q) else None
        return [x for x in self.security_master(ex)['items'] if q in x['name'].lower() or q in x['code']][:30]
    def history(self, code, start='20200101', end=None,refresh=False):
        if not re.fullmatch(r'\d{6}', code):
            raise UserError('股票代码须为6位数字。')
        end = end or today().strftime('%Y%m%d')
        def load():
            from . import provider as ak
            symbol = ('sh' if code.startswith('6') else 'bj' if code.startswith(('4','8','9')) else 'sz') + code
            df = ak.call('stock_zh_a_daily',symbol=symbol,start_date=start,end_date=end,adjust='')
            provider='新浪不复权日线（生产优先）'
            if not {'date','open','high','low','close','volume'}.issubset(df.columns):
                raise DataUnavailable('日线字段不完整。')
            df['date']=pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return {'items':records(df[['date','open','high','low','close','volume']]), 'code':code, 'provider':provider,
                    'date_note':'未复权价格；分红送转会影响收益，不用于宣称真实投资回报。'}
        return self.cached(f'history:{code}:{start}:{end}', 3600, 'AKShare 不复权日线', load,refresh=refresh)
    def company(self,code):
        matches=[x for x in self.search(code) if x['code']==code]
        if not matches:raise DataUnavailable('暂无可靠公司基础资料。')
        x=matches[0]
        info={'股票代码':code,'股票简称':x['name'],'交易所':x.get('exchange'),
              '上市时间':x.get('listing_date') or '暂无可靠数据','行业':x.get('industry') or '暂无可靠数据',
              '总股本':x.get('total_shares') or '暂无可靠数据'}
        return {'items':[info],'source':x['source'],'fetched_at':x['fetched_at'],'stale':x['stale'],
                'date_note':'基础资料来自证券名单；未提供的字段不从模型或价格推断。'}
    def financials(self, code,refresh=False):
        def load():
            from .provider import call
            df=call('sina_financial_summary',symbol=code)
            return {'items':records(df), 'code':code,
                    'date_note':'按原始报表期展示；报表期不等于公告日。禁止用于历史财务选股回测。'}
        return self.cached('financial:'+code, 21600, '新浪财务摘要（AKShare）', load,refresh=refresh)
    def sectors(self,concept=False):
        return self.cache_only('sectors:'+str(concept),force_stale=True)
    def members(self,name,concept=False):
        return self.cache_only('members:'+str(concept)+':'+name,force_stale=True)
    def policies(self,refresh=False):
        def load():
            from .provider import call
            return {'items':records(call('government_policy_index')),
                    'date_note':'官方政策索引；未抓取全文的条目不可作已验证影响分析。'}
        if not refresh:
            try:return self.cache_only('policies:v2')
            except DataUnavailable:return self.cache_only('policies:v1',force_stale=True)
        return self.cached('policies:v2', 3600, 'https://www.gov.cn/zhengce/zuixin/', load, 'policies', refresh=refresh)
    @staticmethod
    def compact_financials(data):
        items=[]
        for row in data['items'][:40]:
            keys=list(row)
            identity=[k for k in keys if not re.fullmatch(r'\d{4}[-/]?\d{2}[-/]?\d{2}',k)]
            dates=sorted([k for k in keys if k not in identity],reverse=True)[:3]
            items.append({k:row[k] for k in identity+dates})
        return dict(data,items=items)
    @staticmethod
    def quality_metrics(data):
        metrics={}
        for row in data['items']:
            label=financial_label(row.get('指标',''))
            dates=sorted([k for k in row if re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}',k)],reverse=True)
            if not dates:continue
            value=number(row[dates[0]])
            if label in ('净资产收益率(ROE)','净资产收益率(ROE)(%)','净资产收益率','加权净资产收益率','加权平均净资产收益率','净资产收益率(加权)','净资产收益率(加权平均)','净资产收益率-加权'):
                metrics['roe']=value
            if label in ('归母净利润','归母净利润(元)','净利润','归属于母公司股东的净利润','归属母公司股东的净利润'):
                metrics['profit']=value
        return metrics
    def policy_detail(self,url):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!='www.gov.cn' or parsed.username or parsed.port not in (None,443):
            raise UserError('仅支持中国政府网 HTTPS 官方原文。')
        def load():
            with httpx.Client(timeout=20,follow_redirects=False) as client:
                with client.stream('GET',url) as response:
                    response.raise_for_status()
                    chunks=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>2_000_000:raise DataUnavailable('原文过大。')
                        chunks.append(chunk)
            soup=BeautifulSoup(b''.join(chunks),'html.parser')
            article=soup.select_one('#UCAP-CONTENT') or soup.select_one('.pages_content')
            if article is None:raise DataUnavailable('未识别官方正文。')
            text_=article.get_text('\n',strip=True)
            title=soup.title.get_text(strip=True) if soup.title else '官方政策原文'
            return {'items':[{'title':title,'url':url,'text':text_[:16000],
                'truncated':len(text_)>16000,'status':'征求意见' if '征求意见' in title else '请依据正文核对生效状态'}],
                'date_note':'日期、部门和具体措施以所附官方原文为准。'}
        import hashlib
        return self.cached('policy:'+hashlib.sha256(url.encode()).hexdigest(),86400,url,load)

    def business(self,code,refresh=False):
        def load():
            from .provider import call
            symbol=('SH' if code.startswith('6') else 'SZ' if code.startswith(('0','3')) else 'BJ')+code
            df=call('stock_zygc_em',symbol=symbol)
            df['报告日期']=pd.to_datetime(df['报告日期']).dt.strftime('%Y-%m-%d')
            latest=df['报告日期'].max()
            return {'items':records(df[df['报告日期']==latest]),'code':code,
                'date_note':'主营构成按所示报告日期披露；不同分类口径不可叠加。'}
        return self.cached('business:'+code,86400,'东方财富主营构成（AKShare）',load,refresh=refresh)
    @staticmethod
    def financial_summary(data):
        aliases={
            '营业收入':('营业总收入','营业收入'), '净利润':('归母净利润','归属母公司股东的净利润','归属于母公司股东的净利润','净利润'),
            'ROE':('净资产收益率(ROE)','净资产收益率','加权净资产收益率','加权平均净资产收益率','净资产收益率(加权)','净资产收益率(加权平均)','净资产收益率-加权'), '毛利率':('销售毛利率','毛利率'),
            '资产负债率':('资产负债率',), '经营现金流':('经营活动产生的现金流量净额','经营活动现金流量净额')}
        result={name:{'value':None,'report_date':None} for name in aliases}
        for row in data['items']:
            label=financial_label(row.get('指标',''))
            dates=sorted([k for k in row if re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}',k)],reverse=True)
            if not dates:continue
            for name,options in aliases.items():
                if label in options:
                    result[name]={'value':number(row[dates[0]]),'report_date':dates[0]}
        return result


def read_home_sections(data,refresh=False):
    """Independent public reads only. No Streamlit API calls from worker threads."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    def read(name):
        start=time.monotonic()
        try:result=getattr(data,name)(refresh=True) if refresh and name in ('indices','policies') else getattr(data,name)()
        except Exception as exc:result=exc
        return {'result':result,'elapsed_seconds':round(time.monotonic()-start,3)}
    names=('indices','policies') if refresh else ('indices','spot','policies')
    with ThreadPoolExecutor(max_workers=3) as executor:
        return dict(zip(names,executor.map(read,names)))
