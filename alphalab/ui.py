from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError
from .config import Settings, SetupRequired, UserError
from .db import today
from .auth import Auth
from .repository import Repository
from .data import MarketData, DataUnavailable, number
from .ai import AI
from .research import screen, RULES, position_metrics, observation_returns
from .trading import paper_order, backtest

DISCLAIMER='仅供学习与研究，不构成投资建议。观察名单不是买入指令；模拟交易不连接证券账户。'

def source(data):
    st.caption(f"来源：{data.get('provider',data.get('source','未提供'))} · 抓取时间：{data.get('fetched_at','未知')}")
    if data.get('date_note'):
        st.caption(data['date_note'])
    if data.get('stale'):
        st.warning('接口暂不可用，正在显示可能过时的历史缓存。')

def fmt(value, suffix=''):
    n=number(value)
    return '暂无可靠数据' if n is None else f'{n:,.2f}{suffix}'

def show_stock(x):
    with st.container(border=True):
        st.markdown(f"**{x.get('name','')} · {x.get('code','')}**")
        change=number(x.get('change_pct'))
        st.write('最新可用价格：'+fmt(x.get('price'),'元'))
        if change is not None:
            st.markdown(f"涨跌幅： :{'red' if change>=0 else 'green'}[{change:+.2f}%]")
        if x.get('reason'):
            st.write(x['reason'])
        if x.get('risk'):
            st.caption(x['risk'])

def ai_button(ai, purpose, label, evidence, question='', level='零基础', key=None):
    key=key or purpose
    if st.button(label,key='generate_'+key,type='primary',use_container_width=True):
        with st.spinner('正在根据有来源的数据生成研究…'):
            answer,cached=ai.generate(purpose,question,evidence,level)
            st.session_state['answer_'+key]=answer
            st.caption('已读取当日相同请求缓存。' if cached else '已保存到研究历史。')
    if 'answer_'+key in st.session_state:
        st.markdown(st.session_state['answer_'+key])
        st.caption('AI内容是辅助分析，仍需核对数据和原文。')

def fetch_panel(loader):
    try:
        with st.spinner('读取公开数据…'):
            result=loader()
        source(result)
        return result
    except DataUnavailable as exc:
        st.warning(str(exc))
        return None

def login_screen(auth):
    st.subheader('欢迎回到你的研究空间')
    st.caption('手机号仅作为登录标识，不验证号码归属。仅接受管理员邀请。')
    tab1,tab2=st.tabs(['登录','邀请注册'])
    with tab1:
        with st.form('login'):
            phone=st.text_input('手机号',max_chars=16)
            password=st.text_input('密码',type='password',max_chars=128)
            submitted=st.form_submit_button('登录',use_container_width=True)
        if submitted:
            st.session_state['token']=auth.login(phone,password)
            st.rerun()
    with tab2:
        with st.form('register'):
            phone=st.text_input('受邀手机号',max_chars=16)
            code=st.text_input('邀请码',type='password')
            password=st.text_input('设置密码（至少12字符）',type='password',max_chars=128)
            repeat=st.text_input('重复密码',type='password',max_chars=128)
            submitted=st.form_submit_button('创建账户',use_container_width=True)
        if submitted:
            if password!=repeat:
                raise UserError('两次密码不一致。')
            auth.register(phone,password,code)
            st.success('注册成功，请在登录页登录。')

def home(data,ai,level):
    st.subheader('每天，看懂一点市场。')
    st.write('先了解大盘，再看行业和公司。这里的每一个数字，都应该有出处。')
    from .data import read_home_sections
    if st.button('更新可用公共源（新浪指数与官方政策）',use_container_width=True):
        with st.spinner('首次读取可用源，旧缓存仍会保留…'):
            updated=read_home_sections(data,refresh=True)
            for entry in updated.values():
                if isinstance(entry['result'],DataUnavailable):st.info(str(entry['result']))
    st.caption('首页优先显示缓存，不自动重试生产失败源；首次无缓存请手动更新。')
    with st.spinner('并行读取指数、市场和政策；首次没有缓存可能需要等待…'):
        sections=read_home_sections(data)
    def section(name):
        entry=sections[name]
        st.caption(f"本次读取耗时：{entry['elapsed_seconds']:.3f} 秒（含缓存/上游等待）")
        if isinstance(entry['result'],Exception):raise entry['result']
        return entry['result']
    indices=fetch_panel(lambda:section('indices'))
    if indices:
        for x in indices['items']:
            with st.container(border=True):
                st.metric(x['name'],fmt(x['price']),f"{x['change_pct']:+.2f}%",delta_color='inverse')
                st.caption('有效数据日期：'+x['date'])
    st.markdown('#### A股市场快照')
    spot=fetch_panel(lambda:section('spot'))
    if spot:
        valid=[number(x.get('change_pct')) for x in spot['items']]
        valid=[x for x in valid if x is not None]
        amounts=[number(x.get('turnover')) for x in spot['items']]
        st.write(f"上涨 {sum(x>0 for x in valid)} 家 · 下跌 {sum(x<0 for x in valid)} 家 · 平盘 {sum(x==0 for x in valid)} 家")
        st.write('快照成交额汇总：'+fmt(sum(x for x in amounts if x is not None)/1e8,'亿元'))
        st.caption('按返回股票汇总，可能不等同于交易所官方市场口径。')
    st.markdown('#### 政策动态')
    policies=fetch_panel(lambda:section('policies'))
    if policies:
        policy_cards(policies['items'])
    evidence={}
    if indices: evidence['indices']=indices
    if spot: evidence['market_snapshot']={k:v for k,v in spot.items() if k!='items'} | {'up':sum(x>0 for x in valid),'down':sum(x<0 for x in valid)}
    if policies: evidence['policies']=policies
    if evidence:
        ai_button(ai,'market','生成今日市场简报',evidence,level=level)

def policy_cards(items):
    for p in items[:6]:
        with st.expander(p['title']):
            st.write(p['publisher'])
            st.caption(f"{p['published_at']} · {p['status']}")
            st.write(p['content'])
            st.link_button('阅读官方原文',p['url'],use_container_width=True)
            st.caption('相关行业、具体措施及公司影响需核对全文和主营业务后分析。')

def sectors(data,repo,ai,level):
    st.subheader('从行业开始认识市场')
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
    st.subheader('有依据的观察名单')
    st.write('真实数据 → 基础过滤 → 规则筛选 → AI解释。没有合适结果时，保留空名单。')
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

def stock_research(data,repo,ai,level):
    st.subheader('认识一家公司')
    if st.button('更新基础证券名单（交易所公开列表）'):
        fetch_panel(lambda:data.security_master(refresh=True))
    query=st.text_input('输入股票名称、代码或关键词',placeholder='例如：梅雁、600868')
    if not query:return
    matches=data.search(query)
    if not matches:
        st.info('当前已取得的基础名单中未匹配；部分交易所可能暂不可用，请换关键词或更新名单。');return
    lookup={f"{x['name']} · {x['code']}":x for x in matches}
    choice=st.selectbox('搜索结果',list(lookup));stock=lookup[choice];code=stock['code']
    source(stock)
    st.caption('基础证券名单独立于快照；价格暂不可用时仍可研究公司。')
    show_stock(stock)
    if st.button('更新该公司研究数据（新浪日线、财务与主营）'):
        from concurrent.futures import ThreadPoolExecutor
        with st.spinner('并行更新已验证数据链，失败保留旧缓存…'):
            loaders=[lambda:data.history(code,refresh=True),lambda:data.financials(code,refresh=True),lambda:data.business(code,refresh=True)]
            def update(loader):
                try:loader();return True
                except DataUnavailable:return False
            with ThreadPoolExecutor(max_workers=3) as executor:success=list(executor.map(update,loaders))
        st.caption(f'本次成功更新 {sum(success)}/3 类数据；失败项不生成替代数值。')
    if st.button('加入自选',use_container_width=True):
        repo.put('watchlist_items',code,{'code':code,'name':stock['name']});st.success('已加入自选。')
    info=fetch_panel(lambda:data.company(code))
    if info:
        for k,v in info['items'][0].items():st.write(f'{k}：{v}')
    business=fetch_panel(lambda:data.business(code))
    if business:
        with st.expander('公司靠什么赚钱：最新披露的主营构成'):
            for item in business['items'][:15]:
                st.write(str(item.get('主营构成',''))+' · '+str(item.get('分类类型','')))
                st.caption('报告日期：'+str(item.get('报告日期','未知'))+' · 主营收入：'+fmt(item.get('主营收入')))
    history=fetch_panel(lambda:data.history(code))
    if history:
        df=pd.DataFrame(history['items'])
        st.plotly_chart(px.line(df,x='date',y='close',labels={'date':'日期','close':'不复权收盘价（元）'}),use_container_width=True)
        st.caption('最近日线日期：'+str(history['items'][-1]['date']))
    financial=fetch_panel(lambda:data.financials(code))
    if financial:
        glossary={'营业收入':'公司卖产品或服务获得的收入，不等于利润。','净利润':'扣除成本费用后剩余的利润。','ROE':'股东投入的资金产生利润的能力，越高不一定越安全。','毛利率':'收入减去直接成本后占收入的比例。','资产负债率':'公司资产中由负债支撑的比例，需结合行业看。','经营现金流':'日常经营实际流入减去流出的现金。'}
        for name,metric in data.financial_summary(financial).items():
            st.write(name+'：'+fmt(metric['value']))
            st.caption(glossary[name])
            if metric['report_date']:st.caption('报表日期：'+metric['report_date']+'；单位见原始指标名称')
        with st.expander('原始财务摘要与报表日期'):
            st.dataframe(pd.DataFrame(financial['items']),hide_index=True,use_container_width=True)
        st.caption('ROE指股东投入的资金产生利润的能力；PE是价格相对盈利的倍数，PB是价格相对净资产的倍数。')
    st.write('动态PE：'+fmt(stock.get('pe'))+' · PB：'+fmt(stock.get('pb')))
    evidence={'stock':stock,'company':info,'business':business,'financials':financial,
              'latest_bars':dict(history,items=history['items'][-20:]) if history else None}
    # Limit transposed financial table to latest report columns.
    if financial:evidence['financials']=data.compact_financials(financial)
    ai_button(ai,'stock','生成AI研究报告',evidence,stock['name']+' '+code,level,key='stock_'+code)

def portfolio(data,repo):
    st.markdown('#### 我的持仓')
    st.caption('手动记录，不连接券商。相同代码可录入多个批次。')
    with st.form('position'):
        code=st.text_input('股票代码',max_chars=6)
        qty=st.number_input('持仓数量（股）',min_value=1,step=1)
        cost=st.number_input('每股成本（元）',min_value=.01,step=.01)
        day=st.date_input('买入日期',max_value=today())
        save=st.form_submit_button('添加持仓',use_container_width=True)
    if save:
        found=[x for x in data.search(code) if x['code']==code]
        if not found:raise UserError('未找到该股票，未保存持仓。')
        repo.put('portfolio_positions',str(uuid4()),{'code':code,'name':found[0]['name'],'quantity':qty,'cost':cost,'buy_date':str(day)})
        st.success('已保存。')
    positions=repo.list('portfolio_positions')
    if not positions:st.info('还没有持仓记录。');return
    quotes=fetch_panel(data.spot)
    mapping={x['code']:x.get('price') for x in quotes['items']} if quotes else {}
    rows,incomplete=position_metrics([r['payload'] for r in positions],mapping)
    if incomplete:st.warning('部分行情缺失，暂不计算完整集中度。')
    by_code={}
    for x in rows:
        if x['weight_pct'] is not None:by_code[x['code']]=by_code.get(x['code'],0)+x['weight_pct']
    if any(w>40 for w in by_code.values()):st.warning('单只股票占已记录持仓市值超过40%，请关注集中风险。')
    for record,x in zip(positions,rows):
        with st.expander(f"{x['name']} · {x['quantity']}股"):
            st.write('市值：'+fmt(x['market_value'])+' · 浮盈亏：'+fmt(x['pnl'])+' · 收益率：'+fmt(x['return_pct'],'%'))
            st.write('占比：'+fmt(x['weight_pct'],'%'))
            with st.form('edit_'+record['key']):
                q=st.number_input('修改数量',min_value=1,value=int(x['quantity']))
                c=st.number_input('修改成本',min_value=.01,value=float(x['cost']))
                if st.form_submit_button('保存修改'):
                    repo.put('portfolio_positions',record['key'],{**record['payload'],'quantity':q,'cost':c});st.rerun()
            if st.button('删除此持仓',key='delpos_'+record['key']):repo.remove('portfolio_positions',record['key']);st.rerun()

def history_page(repo,data):
    st.markdown('#### 研究历史')
    query=st.text_input('搜索历史报告')
    for r in repo.list('research_reports'):
        p=r['payload']
        if query and query.lower() not in str(p).lower():continue
        with st.expander(f"{p.get('question') or p.get('purpose')} · {str(r['created_at'])[:16]}"):
            st.caption('历史研究，不代表最新观点或最新行情。')
            st.markdown(p['answer'])
            if st.button('删除报告',key='delreport_'+r['key']):repo.remove('research_reports',r['key']);st.rerun()
    st.markdown('#### 历史观察名单')
    for r in repo.list('screening_runs',limit=20):
        p=r['payload']
        with st.expander(p['strategy']+' · '+p['created_at']):
            st.caption(p['scope'])
            for x in p['items']:
                show_stock(x)
                if st.button('统计后续1/5/20日表现',key='perf_'+r['key']+x['code']):
                    history=data.history(x['code'])
                    source(history)
                    st.json(observation_returns(history['items'],p['created_at'],float(x['price'])))
                    st.caption('从保存日之后的交易日起算，未扣成本、未复权；不足期数显示null。快照时点不保证可成交。')

def chat(repo,ai,level):
    st.markdown('#### 和研究助手聊一聊')
    st.caption('记忆按当前问题检索；历史事实保留日期。聊天不默认获取实时行情。')
    sessions=repo.list('chat_sessions',limit=30)
    choices={'新对话':None}|{str(r['payload'].get('title','对话'))+' · '+r['key'][:6]:r['key'] for r in sessions}
    selected=st.selectbox('对话',list(choices))
    sid=choices[selected]
    messages=repo.list('chat_messages',limit=500)
    messages=sorted([r for r in messages if r['payload'].get('session_id')==sid],key=lambda x:x['created_at']) if sid else []
    for r in messages:
        with st.chat_message(r['payload']['role']):st.markdown(r['payload']['content'])
    question=st.chat_input('例如：什么是市盈率？',max_chars=3000)
    if question:
        sid=sid or str(uuid4())
        repo.put('chat_sessions',sid,{'title':question[:40]})
        turn=str(uuid4())
        repo.put('chat_messages',turn,{'session_id':sid,'role':'user','content':question})
        with st.spinner('思考中…'):
            answer,_=ai.generate('chat',question,{'recent_conversation':[r['payload'] for r in messages[-8:]],
                'current_sources':[],'data_note':'本次未附实时市场证据'},level,request_id=turn)
        repo.put('chat_messages',str(uuid4()),{'session_id':sid,'role':'assistant','content':answer})
        repo.put('user_memories',turn,{'question':question,'answer':answer[:2000],'date':today().isoformat()})
        st.markdown(answer);st.success('对话与相关记忆已保存。')
    if sid and st.button('删除指定对话'):
        for r in messages:repo.remove('chat_messages',r['key'])
        repo.remove('chat_sessions',sid)
        st.success('对话已删除；可在记忆管理中删除相关长期记忆。')
    if st.checkbox('确认清空全部聊天历史') and st.button('清空聊天'):
        repo.remove('chat_messages');repo.remove('chat_sessions');st.rerun()

def simulation(data,repo):
    st.markdown('#### 模拟交易')
    st.warning('仅教育记账：以最近已发布日线收盘价加滑点计算，不能验证盘中可成交性。仅支持非ST沪深主板。')
    account=repo.get('portfolios','paper',{'cash':'100000','lots':[]})
    st.metric('模拟可用资金',fmt(account['cash'],'元'))
    for x in account['lots']:st.write(f"{x['code']} · {x['quantity']}股 · 成交数据日{x['date']}")
    if account['lots']:
        quotes=fetch_panel(data.spot)
        if quotes:
            prices={x['code']:number(x.get('price')) for x in quotes['items']}
            if all(prices.get(x['code']) is not None for x in account['lots']):
                value=sum(prices[x['code']]*x['quantity'] for x in account['lots'])
                equity=float(account['cash'])+value
                st.write(f'模拟总资产：{equity:,.2f}元 · 累计盈亏：{equity-100000:+,.2f}元 · 收益率：{(equity/100000-1)*100:+.2f}%')
            else:st.info('行情不完整，无法计算模拟账户总收益。')
    else:
        st.write(f"累计已结算盈亏：{float(account['cash'])-100000:+,.2f}元")
    with st.form('paper'):
        code=st.text_input('模拟股票代码',max_chars=6)
        side=st.selectbox('方向',['buy','sell'],format_func=lambda x:'模拟买入' if x=='buy' else '模拟卖出')
        qty=st.number_input('模拟数量',min_value=100,step=100)
        submitted=st.form_submit_button('记录模拟交易')
    if submitted:
        matches=[x for x in data.search(code) if x['code']==code and 'ST' not in x['name'].upper() and '退' not in x['name']]
        if not matches or matches[0].get('stale'):raise UserError('证券身份资料缺失或过时，不能模拟成交；请先更新基础名单。')
        bars=data.history(code)
        if bars.get('stale') or (today()-date.fromisoformat(bars['items'][-1]['date'])).days>10:
            raise UserError('行情过时，拒绝模拟成交。')
        source(bars)
        # Form reruns are protected by an order nonce rotated after successful settlement.
        nonce=st.session_state.setdefault('paper_nonce',str(uuid4()))
        trade=paper_order(repo,code,side,int(qty),bars['items'],nonce)
        st.session_state['paper_nonce']=str(uuid4())
        st.success('模拟交易已记录。');st.json(trade)
    with st.expander('交易流水'):
        for r in repo.list('simulated_trades'):st.json(r['payload'])

def backtest_page(data,repo):
    st.markdown('#### 实验性策略回测')
    st.caption('双均线：昨日收盘信号，次日开盘成交；样本内与样本外分别从现金开始，不使用未来财务数据。')
    with st.form('backtest'):
        code=st.text_input('回测股票代码',max_chars=6)
        start=st.date_input('起始日期',value=today()-timedelta(days=730),max_value=today())
        end=st.date_input('结束日期',value=today(),max_value=today())
        fast=st.number_input('短均线天数',min_value=2,max_value=249,value=5)
        slow=st.number_input('长均线天数',min_value=3,max_value=250,value=20)
        submitted=st.form_submit_button('运行实验回测')
    if submitted:
        if start>=end:raise UserError('起始日期应早于结束日期。')
        stock=[x for x in data.search(code) if x['code']==code]
        if not stock or stock[0].get('stale') or 'ST' in stock[0]['name'].upper():raise UserError('请选择已核实的非ST沪深主板股票。')
        history=data.history(code,start.strftime('%Y%m%d'),end.strftime('%Y%m%d'));source(history)
        result=backtest(history['items'],code,int(fast),int(slow))
        result['source']={k:v for k,v in history.items() if k!='items'}
        # Retain exact input for reproducibility, including vendor revisions.
        result['bars']=history['items']
        repo.put('strategy_results',str(uuid4()),result)
        st.warning(result['warning'])
        for label,k in [('样本内','in_sample'),('样本外','out_of_sample')]:
            st.write(label);r=result[k]
            st.write(f"策略收益 {r['return_pct']:+.2f}% · 同股持有基准（未扣费） {r['benchmark_pct']:+.2f}% · 最大回撤 {r['max_drawdown_pct']:.2f}% · 成本 {r['costs']:.2f}元")
            st.plotly_chart(px.line(pd.DataFrame(r['curve']),x='date',y='equity'),use_container_width=True)
            st.json(r['forward_returns_pct'])
    for r in repo.list('strategy_results',limit=10):
        with st.expander('已保存回测 · '+str(r['created_at'])[:16]):
            st.json({k:v for k,v in r['payload'].items() if k not in ('bars','in_sample','out_of_sample')})
            st.download_button('下载完整复现数据',data=__import__('json').dumps(r['payload'],ensure_ascii=False),file_name='alphalab-backtest.json',key='download_'+r['key'])

def admin(repo,auth):
    # Every admin method performs fresh server-side authorization.
    users=repo.admin_users()
    st.subheader('管理后台')
    with st.expander('数据源诊断（只读，仅管理员）'):
        from .market_diagnostics import PROBES, probe_report_for_admin
        from .network_diagnostics import GROUPS, report_for_admin
        group=st.selectbox('域名网络诊断分组',list(GROUPS))
        if st.button('检查该组DNS/TCP/TLS/HTTPS（只读）'):
            with st.spinner('分阶段检测公开目标，最多3个并发；结果冷却60秒…'):
                results=report_for_admin(repo,group)
            st.dataframe(pd.DataFrame(results),hide_index=True,use_container_width=True)
            st.caption('秒数为各阶段实际等待时间；HTTPS只测连通性，不读取正文、不代表业务数据正常。PROXY_ROUTE表示保留平台代理，不直连绕过；403不能单独证明地区限制。')
        endpoint=st.selectbox('选择单个公开接口',list(PROBES))
        st.caption('从本应用所在云环境测试；单次最多约12秒。同一接口结果保留30秒。不显示请求或响应详情，不写行情缓存。')
        if st.button('运行只读数据源诊断',use_container_width=True):
            with st.spinner('正在诊断所选接口…'):
                report=probe_report_for_admin(repo,endpoint)
            st.json(report)
            st.caption('CONNECTED仅说明本次接口调用和必要字段检查通过，不证明实时性或以后持续可用。403/429也不能单独证明地区限制。')
    st.success('数据库查询正常。')
    st.caption('DeepSeek密钥：'+('已配置（不代表连接验证通过）' if auth.settings.deepseek_api_key else '待配置'))
    st.caption(f'平台每日上限：{auth.settings.platform_daily_calls}次 · 每日预算：{auth.settings.daily_budget}元；在服务端Secrets中调整。')
    with st.form('invite'):
        phone=st.text_input('受邀手机号')
        if st.form_submit_button('生成3天有效的邀请码'):
            st.code(auth.invite(repo.token,phone));st.caption('仅本次显示；请通过安全渠道转交受邀人。')
    for user in users:
        st.write(f"{str(user['phone'])[:3]}****{str(user['phone'])[-4:]} · {'管理员' if user['is_admin'] else '普通用户'}")
        if not user['is_admin']:
            with st.form('user_'+str(user['id'])):
                enabled=st.checkbox('启用账户',value=user['enabled'])
                quota=st.number_input('每日AI调用额度',min_value=0,max_value=10000,value=user['daily_calls'])
                if st.form_submit_button('保存用户设置'):
                    repo.admin_update(user['id'],enabled,int(quota));st.success('已保存。')
    logs=repo.admin_usage()
    st.caption('仅显示额度、Token及费用，不提供其他用户私人聊天或持仓。未知调用保留预估预算。')
    st.dataframe(pd.DataFrame(logs),hide_index=True,use_container_width=True)
    if st.button('清除公共数据缓存'):repo.clear_cache();st.success('已清除，私人数据不受影响。')

def mine(data,repo,ai,auth,user):
    pref=repo.get('user_preferences','profile',{'level':'零基础'})
    section=st.selectbox('我的研究空间',['持仓','自选','聊天','研究历史','模拟交易','策略回测','个人设置','记忆管理']+(['管理后台'] if user['is_admin'] else []))
    if section=='持仓':portfolio(data,repo)
    elif section=='自选':
        for r in repo.list('watchlist_items'):
            st.write(r['payload']['name']+' · '+r['payload']['code'])
            if st.button('移除',key='watch_'+r['key']):repo.remove('watchlist_items',r['key']);st.rerun()
    elif section=='聊天':chat(repo,ai,pref['level'])
    elif section=='研究历史':history_page(repo,data)
    elif section=='模拟交易':simulation(data,repo)
    elif section=='策略回测':backtest_page(data,repo)
    elif section=='管理后台':admin(repo,auth)
    elif section=='记忆管理':
        for r in repo.list('user_memories'):
            with st.expander(r['key']):
                st.json(r['payload'])
                if st.button('删除记忆',key='mem_'+r['key']):repo.remove('user_memories',r['key']);st.rerun()
    elif section=='个人设置':
        level=st.selectbox('知识水平',['零基础','进阶','专业'],index=['零基础','进阶','专业'].index(pref['level']))
        if st.button('保存偏好'):repo.put('user_preferences','profile',{'level':level});st.success('已保存。')
        with st.form('password'):
            old=st.text_input('原密码',type='password');new=st.text_input('新密码',type='password')
            if st.form_submit_button('修改密码并使所有会话失效'):
                auth.change_password(repo.token,old,new);st.session_state.clear();st.rerun()

def main():
    st.set_page_config(page_title='AlphaLab · 让投资研究变得简单',page_icon='◈',layout='wide',initial_sidebar_state='collapsed')
    st.markdown('<style>'+Path('assets/styles.css').read_text()+'</style>',unsafe_allow_html=True)
    st.title('AlphaLab')
    st.caption('让投资研究变得简单。')
    try:
        settings=Settings.load(st.secrets)
        auth=Auth(settings)
        token=st.session_state.get('token')
        if not token:
            login_screen(auth);return
        user=auth.current(token)
        repo=Repository(auth,token);data=MarketData(auth.db);ai=AI(repo,settings)
        pref=repo.get('user_preferences','profile',{'level':'零基础'})
        # Native selectbox is reliable at narrow widths and keyboard/screen-reader accessible.
        page=st.selectbox('导航',['首页','行业','选股','个股','我的'],label_visibility='collapsed')
        if st.button('退出登录'):
            auth.logout(token);st.session_state.clear();st.rerun()
        if page=='首页':home(data,ai,pref['level'])
        elif page=='行业':sectors(data,repo,ai,pref['level'])
        elif page=='选股':screener(data,repo,ai,pref['level'])
        elif page=='个股':stock_research(data,repo,ai,pref['level'])
        else:mine(data,repo,ai,auth,user)
    except (UserError,SetupRequired) as exc:
        st.warning(str(exc))
        if '会话已过期' in str(exc):
            st.session_state.clear()
            if st.button('返回登录'):st.rerun()
    except SQLAlchemyError:
        st.error('数据库安全连接配置未完成或数据库暂时不可用。请检查部署平台的官方 CA 和连接配置。')
    except Exception:
        # Avoid leaking SQL, DB URLs, phone numbers or upstream response bodies.
        st.error('服务暂不可用。请检查数据库迁移、网络和管理员配置后重试；未展示敏感错误详情。')
    finally:
        st.divider();st.caption(DISCLAIMER)
