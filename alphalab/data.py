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

def fetch_policy_index():
    url='https://www.gov.cn/zhengce/zuixin/'
    with httpx.Client(timeout=httpx.Timeout(5,connect=3), follow_redirects=False) as client:
        r=client.get(url)
        r.raise_for_status()
    soup=BeautifulSoup(r.content, 'html.parser')
    items=[]
    for li in soup.select('li'):
        a=li.find('a',href=True)
        if not a:
            continue
        link=urljoin(url,a['href'])
        title=a.get_text(' ',strip=True)
        date=re.search(r'20\d{2}[-/]\d{2}[-/]\d{2}',li.get_text(' ',strip=True))
        if urlparse(link).hostname!='www.gov.cn' or not date or len(title)<8:
            continue
        items.append({'title':title,'url':link,'published_at':date.group(0),
            'publisher':'中国政府网（汇总入口；具体发文部门请核对原文）',
            'status':'征求意见' if '征求意见' in title else '待核对原文',
            'content':'请打开官方原文核对具体措施，标题不构成完整政策依据。'})
    return {'items':items[:20], 'date_note':'官方政策索引；未抓取全文的条目不可作已验证影响分析。'}

class MarketData:
    def __init__(self, db):
        self.db = db
    def cached(self, key, ttl, source, loader, storage=None):
        # Cross-process single-flight: the lock is held until provider result is persisted.
        with self.db.begin() as c:
            lock(c, 'data:' + key)
            row = c.execute(select(cache).where(cache.c.key == key)).mappings().first()
            if row and row['expires_at'] > now():
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
                for i, item in enumerate(payload['items']):
                    itemkey = str(item.get('code', item.get('name', item.get('url', i))))
                    if len(itemkey) > 180:
                        import hashlib
                        itemkey = hashlib.sha256(itemkey.encode()).hexdigest()
                    stmt = insert(t).values(key=itemkey, payload=item, source=source, fetched_at=fetched)
                    c.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={'payload': item, 'source': source, 'fetched_at': fetched}))
            return {**payload, 'fetched_at': fetched.isoformat(), 'stale': False, 'source': source}
    def spot(self):
        def load():
            from . import provider as ak
            try:
                df = ak.call("stock_zh_a_spot_em",)
                provider = '东方财富（AKShare）'
                df = df.rename(columns={'代码':'code','名称':'name','最新价':'price','涨跌幅':'change_pct',
                    '成交额':'turnover','市盈率-动态':'pe','市净率':'pb','总市值':'market_cap'})
            except Exception:
                df = ak.call("stock_zh_a_spot",)
                provider = '新浪财经（AKShare备选）'
                df = df.rename(columns={'代码':'code','名称':'name','最新价':'price','涨跌幅':'change_pct','成交额':'turnover'})
            if not {'code','name','price'}.issubset(df.columns):
                raise DataUnavailable('行情字段不匹配。')
            df['code'] = df['code'].astype(str).str.replace(r'^(sh|sz|bj)', '', regex=True).str.zfill(6)
            items = records(df[[x for x in ('code','name','price','change_pct','turnover','pe','pb','market_cap') if x in df.columns]])
            # Snapshot endpoint has no trusted trading date: never label retrieval time as trading date.
            return {'items': items, 'provider': provider, 'data_date': None,
                    'date_note': '快照接口未提供可信交易日期；抓取时间不等于交易时间，非交易日请核对日线。'}
        return self.cached('spot:v1', 180, 'AKShare：东方财富 / 新浪', load, 'stock_master')
    def indices(self):
        def load():
            from . import provider as ak
            items=[]
            for code, name in [('sh000001','上证指数'),('sz399001','深证成指'),('sz399006','创业板指')]:
                df = ak.call("stock_zh_index_daily_em",symbol=code).tail(2)
                if len(df)<2:
                    continue
                a,b = df.iloc[-2],df.iloc[-1]
                items.append({'code':code, 'name':name, 'price':number(b['close']),
                    'change_pct':(float(b['close'])/float(a['close'])-1)*100, 'date':str(b['date'])})
            return {'items':items, 'date_note':'最近已发布日线，非实时指数。'}
        return self.cached('indices:v1', 900, '东方财富指数日线（AKShare）', load)
    def search(self, query):
        data = self.spot()
        q = query.strip().lower()
        return [s for s in data['items'] if q and (q in s['name'].lower() or q in s['code'])][:30]
    def history(self, code, start='20200101', end=None):
        if not re.fullmatch(r'\d{6}', code):
            raise UserError('股票代码须为6位数字。')
        end = end or today().strftime('%Y%m%d')
        def load():
            from . import provider as ak
            try:
                df = ak.call("stock_zh_a_hist",symbol=code, period='daily', start_date=start, end_date=end, adjust='')
                df = df.rename(columns={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume','成交额':'amount'})
                provider='东方财富不复权日线'
            except Exception:
                symbol = ('sh' if code.startswith('6') else 'bj' if code.startswith(('4','8','9')) else 'sz') + code
                df = ak.call("stock_zh_a_daily",symbol=symbol, start_date=start, end_date=end, adjust='')
                provider='新浪不复权日线（备选）'
            if not {'date','open','high','low','close','volume'}.issubset(df.columns):
                raise DataUnavailable('日线字段不完整。')
            df['date']=pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return {'items':records(df[['date','open','high','low','close','volume']]), 'code':code, 'provider':provider,
                    'date_note':'未复权价格；分红送转会影响收益，不用于宣称真实投资回报。'}
        return self.cached(f'history:{code}:{start}:{end}', 3600, 'AKShare 不复权日线', load)
    def company(self, code):
        def load():
            from . import provider as ak
            df=ak.call("stock_individual_info_em",symbol=code)
            fields=dict(zip(df['item'].astype(str),df['value'].astype(str)))
            return {'items':[fields], 'code':code, 'date_note':'公司信息为抓取时可用版本，不代表历史时点。'}
        return self.cached('company:'+code, 86400, '东方财富公司资料（AKShare）', load)
    def financials(self, code):
        def load():
            from .provider import call
            df=call('sina_financial_summary',symbol=code)
            return {'items':records(df), 'code':code,
                    'date_note':'按原始报表期展示；报表期不等于公告日。禁止用于历史财务选股回测。'}
        return self.cached('financial:'+code, 21600, '新浪财务摘要（AKShare）', load)
    def sectors(self, concept=False):
        def load():
            from . import provider as ak
            df=ak.call("stock_board_concept_name_em",) if concept else ak.call("stock_board_industry_name_em",)
            df=df.rename(columns={'板块名称':'name','板块代码':'code','涨跌幅':'change_pct','总市值':'market_cap'})
            return {'items':records(df), 'date_note':'东方财富行业分类' if not concept else '投资主题标签，非正式行业分类'}
        return self.cached('sectors:'+str(concept), 1800, '东方财富板块（AKShare）', load, 'industries')
    def members(self, name, concept=False):
        def load():
            from . import provider as ak
            df=ak.call("stock_board_concept_cons_em",symbol=name) if concept else ak.call("stock_board_industry_cons_em",symbol=name)
            df=df.rename(columns={'代码':'code','名称':'name','最新价':'price','涨跌幅':'change_pct','成交额':'turnover','市盈率-动态':'pe','市净率':'pb'})
            df['code']=df['code'].astype(str).str.zfill(6)
            return {'items':records(df), 'sector':name}
        return self.cached('members:'+str(concept)+':'+name, 1800, '东方财富板块成分（AKShare）', load)
    def policies(self):
        def load():
            from .provider import call
            return {'items':records(call('government_policy_index')),
                    'date_note':'官方政策索引；未抓取全文的条目不可作已验证影响分析。'}
        return self.cached('policies:v1', 3600, 'https://www.gov.cn/zhengce/zuixin/', load, 'policies')
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
            label=str(row.get('指标',''))
            dates=sorted([k for k in row if re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}',k)],reverse=True)
            if not dates:continue
            value=number(row[dates[0]])
            if label in ('净资产收益率(ROE)','净资产收益率(ROE)(%)','净资产收益率'):
                metrics['roe']=value
            if label in ('归母净利润','归母净利润(元)','净利润'):
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

    def business(self,code):
        def load():
            from .provider import call
            symbol=('SH' if code.startswith('6') else 'SZ' if code.startswith(('0','3')) else 'BJ')+code
            df=call('stock_zygc_em',symbol=symbol)
            df['报告日期']=pd.to_datetime(df['报告日期']).dt.strftime('%Y-%m-%d')
            latest=df['报告日期'].max()
            return {'items':records(df[df['报告日期']==latest]),'code':code,
                'date_note':'主营构成按所示报告日期披露；不同分类口径不可叠加。'}
        return self.cached('business:'+code,86400,'东方财富主营构成（AKShare）',load)
    @staticmethod
    def financial_summary(data):
        aliases={
            '营业收入':('营业总收入','营业收入'), '净利润':('归母净利润','归属母公司股东的净利润','净利润'),
            'ROE':('净资产收益率(ROE)','净资产收益率'), '毛利率':('销售毛利率','毛利率'),
            '资产负债率':('资产负债率',), '经营现金流':('经营活动产生的现金流量净额','经营活动现金流量净额')}
        result={name:{'value':None,'report_date':None} for name in aliases}
        for row in data['items']:
            label=str(row.get('指标','')).replace('(%)','').replace('（%）','').replace('(元)','')
            dates=sorted([k for k in row if re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}',k)],reverse=True)
            if not dates:continue
            for name,options in aliases.items():
                if label in options:
                    result[name]={'value':number(row[dates[0]]),'report_date':dates[0]}
        return result


def read_home_sections(data):
    """Independent public reads only. No Streamlit API calls from worker threads."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    def read(name):
        start=time.monotonic()
        try:result=getattr(data,name)()
        except Exception as exc:result=exc
        return {'result':result,'elapsed_seconds':round(time.monotonic()-start,3)}
    names=('indices','spot','policies')
    with ThreadPoolExecutor(max_workers=3) as executor:
        return dict(zip(names,executor.map(read,names)))
