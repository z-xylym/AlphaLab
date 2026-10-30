from uuid import uuid4
import streamlit as st
from ..config import UserError
from ..db import today
from ..data import DataUnavailable, number
from ..research import screen, RULES
from .components import source, show_stock, ai_button, fetch_panel
from .home import policy_cards

def sectors(data,repo,ai,level):
    from ..personalization import industry_catalog
    from .reads import remember
    from .navigation import open_stock
    from .components import empty_state, research_card, data_meta
    st.header('行业观察')
    st.caption('按已有明确分类浏览公司；行业分类是业务视角，不代表投资建议。没有分类的公司不会由AI补入。')
    catalog=remember('industry_catalog',lambda:industry_catalog(data.db))
    query=st.text_input('搜索行业',placeholder='例如：食品饮料、银行；无需股票代码')
    names=[name for name in catalog['industries'] if query.strip().lower() in name.lower()]
    st.caption(f"已有可靠行业 {len(catalog['industries'])} 个 · 当前匹配 {len(names)} 个")
    if not names:
        empty_state('暂无匹配的可靠行业','可调整关键词；系统不会猜测公司属于哪个行业。')
        return
    name=st.selectbox('选择行业',names)
    data_meta(catalog['industry_sources'][name])
    codes=catalog['industries'][name]
    if not codes:
        empty_state('已有行业名称，暂无可靠公司名单','名单补齐前不展示推测成分。')
        return
    st.caption(f'已保存 {len(codes)} 家公司，按代码排序；不代表完整市场覆盖或公司排名。')
    pages=(len(codes)+19)//20
    page=st.number_input('行业股票页',min_value=1,max_value=pages,value=1,step=1) if pages>1 else 1
    for code in codes[(page-1)*20:page*20]:
        stock=catalog['stocks'][code]
        with st.container(border=True):
            research_card(stock['name'],code+' · '+name,'已有明确行业归属；价格缺失不影响进入研究。','公司观察')
            data_meta(stock)
            quote=catalog['quotes'].get(code,{})
            if quote:
                from .components import fmt
                st.caption('已有价格 '+fmt(quote.get('price'),' 元')+' · 涨跌幅 '+fmt(quote.get('change_pct'),'%'))
                data_meta(catalog['quote_metadata'])
            st.button('查看研究',key='industry_open_'+code,on_click=open_stock,args=(code,))


def screener(data,repo,ai,level):
    st.header('选股观察')
    st.caption('按统一规则筛选，不降低缺失数据标准。')
    board=st.selectbox('市场范围',['全部A股','沪深主板','创业板','科创板'])
    industry=st.text_input('指定行业（可留空；请使用行业页的完整名称）')
    strategy=st.selectbox('研究策略',['低估值','稳健质量','趋势动量'])
    with st.expander('查看统一规则'):
        st.caption('市盈率（PE）：价格相对盈利的比值；市净率（PB）：价格相对净资产的比值。缺少可靠值时不估算。')
        st.caption('ROE：自有资金的盈利效率；成交额：一段时间内买卖股票的总金额。')
        st.caption('需有上市日期、成交额和价格。稳健质量还需可靠ROE和净利润；缺失值不当作0。')
    if st.button('生成观察名单',type='primary',use_container_width=True):
        result=data.members(industry) if industry.strip() else data.spot()
        if result.get('stale'):
            raise UserError('当前为过时缓存，请恢复数据接口后重新筛选。')
        # Deterministic bounded enrichment prevents thousands of upstream calls.
        pool=[dict(x) for x in result['items'] if number(x.get('turnover')) is not None and number(x['turnover'])>=RULES.min_turnover and 'ST' not in x.get('name','').upper()]
        pool=sorted(pool,key=lambda x:x['code'])[:30]
        with st.spinner('核对候选公司的上市时间与财务数据…'):
            for x in pool:
                try:
                    company=data.company(x['code'])
                    info=company['items'][0]
                    x['listing_date']=str(info.get('上市时间','')).removesuffix('.0')
                    x['industry']=info.get('行业','暂无可靠数据')
                    x['company_source']='东方财富公司资料'
                    x['company_fetched_at']=company['fetched_at']
                    if strategy=='稳健质量':
                        financial=data.financials(x['code'])
                        if not financial.get('stale'):
                            x.update(data.quality_metrics(financial))
                            x['financial_fetched_at']=financial['fetched_at']
                except DataUnavailable:
                    pass
        chosen=screen(pool,strategy,board)
        saved={'items':chosen,'strategy':strategy,'board':board,'industry':industry,'rules':RULES.__dict__,
            'source':result['source'],'fetched_at':result['fetched_at'],'created_at':today().isoformat(),
            'scope':'按代码排序的最多30只流动性候选；非全市场穷举'}
        key=str(uuid4());repo.put('screening_runs',key,saved)
        st.session_state['screen_result']=saved
    result=st.session_state.get('screen_result')
    if result:
        source(result);st.caption(result['scope'])
        if not result['items']:st.info('没有股票符合已核实条件；可尝试其他策略，不会自动降低阈值。')
        for x in result['items']:show_stock(x)
        if result['items']:ai_button(ai,'screen','解释这份观察名单',result,level=level)
