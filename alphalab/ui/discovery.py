from uuid import uuid4
import streamlit as st
from ..config import UserError
from ..db import today
from ..data import DataUnavailable, number
from ..research import screen, RULES
from .components import source, show_stock, ai_button, fetch_panel
from .home import policy_cards

def sectors(data,repo,ai,level):
    st.header('行业观察')
    category=st.radio('分类类型',['行业分类（东方财富口径）','投资主题（概念标签）'])
    concept=category.startswith('投资')
    board=fetch_panel(lambda:data.sectors(concept))
    if not board:return
    name=st.selectbox('选择行业或主题',[x['name'] for x in board['items']])
    if st.button('关注此行业',use_container_width=True):
        repo.put('user_memories','sector:'+name,{'kind':'followed_sector','name':name,'category':category})
        st.success('已保存。')
    members=fetch_panel(lambda:data.members(name,concept))
    if members:
        for x in members['items'][:10]:show_stock(x)
        st.caption('仅展示前10个接口返回成分，不代表推荐或龙头排名。')
    policies=fetch_panel(data.policies)
    if policies:
        relevant=[p for p in policies['items'] if name in p['title']]
        policy_cards(relevant)
        if not relevant:st.info('当前官方索引中暂无标题匹配政策；不代表没有相关政策。')
        if relevant and st.button('核对政策全文并分析关联',use_container_width=True):
            detail=data.policy_detail(relevant[0]['url'])
            answer,_=ai.generate('policy',f'{name}相关政策，区分事实与潜在影响',{'policy':detail,'members':dict(members,items=members['items'][:10]) if members else None,'note':'仅候选名单，未验证每家公司的主营业务关联'},level)
            st.markdown(answer)
    if members:
        ai_button(ai,'sector','用大白话解释这个行业',{'sector':name,'category':category,'members':dict(members,items=members['items'][:10])},name,level,key='sector_'+name)

def screener(data,repo,ai,level):
    st.header('选股观察')
    st.caption('按统一规则筛选，不降低缺失数据标准。')
    board=st.selectbox('市场范围',['全部A股','沪深主板','创业板','科创板'])
    industry=st.text_input('指定行业（可留空；请使用行业页的完整名称）')
    strategy=st.selectbox('研究策略',['低估值','稳健质量','趋势动量'])
    with st.expander('查看统一规则'):
        st.json(RULES.__dict__)
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
