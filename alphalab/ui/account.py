from datetime import date, timedelta
from uuid import uuid4
import pandas as pd
import plotly.express as px
import streamlit as st
from ..config import UserError
from ..db import today
from ..data import DataUnavailable, number
from ..research import position_metrics, observation_returns
from ..trading import paper_order, backtest
from .components import source, fmt, show_stock, fetch_panel, chart_style
from .admin import admin

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
    if sid and st.button('删除指定对话',key='danger_delete_chat'):
        for r in messages:repo.remove('chat_messages',r['key'])
        repo.remove('chat_sessions',sid)
        st.success('对话已删除；可在记忆管理中删除相关长期记忆。')
    if st.checkbox('确认清空全部聊天历史') and st.button('清空聊天',key='danger_clear_chat'):
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
            st.plotly_chart(chart_style(px.line(pd.DataFrame(r['curve']),x='date',y='equity')),use_container_width=True)
            st.json(r['forward_returns_pct'])
    for r in repo.list('strategy_results',limit=10):
        with st.expander('已保存回测 · '+str(r['created_at'])[:16]):
            st.json({k:v for k,v in r['payload'].items() if k not in ('bars','in_sample','out_of_sample')})
            st.download_button('下载完整复现数据',data=__import__('json').dumps(r['payload'],ensure_ascii=False),file_name='alphalab-backtest.json',key='download_'+r['key'])

def mine(data,repo,ai,auth,user,pref=None):
    st.header('我的')
    st.caption('自选、持仓与研究记录')
    with st.expander('账户'):
        st.caption('当前账户已登录')
        if st.button('退出登录'):
            auth.logout(repo.token);st.session_state.clear();st.rerun()
    pref=pref or repo.get('user_preferences','profile',{'level':'零基础'})
    section=st.selectbox('我的研究空间',['持仓','自选','聊天','研究历史','模拟交易','策略回测','个人设置','记忆管理']+(['管理后台'] if user['is_admin'] else []))
    if section=='持仓':portfolio(data,repo)
    elif section=='自选':
        for r in repo.list('watchlist_items'):
            st.write(r['payload']['name']+' · '+r['payload']['code'])
            if st.button('移除',key='remove_'+r['key']):repo.remove('watchlist_items',r['key']);st.rerun()
    elif section=='聊天':chat(repo,ai,pref['level'])
    elif section=='研究历史':history_page(repo,data)
    elif section=='模拟交易':simulation(data,repo)
    elif section=='策略回测':backtest_page(data,repo)
    elif section=='管理后台':admin(data,repo,auth)
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
