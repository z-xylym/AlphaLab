import streamlit as st
from ..personalization import industry_catalog, recommend
from ..data import number
from .reads import remember
from .navigation import open_stock
from .components import research_card, metric_grid, fmt, data_meta, empty_state


def recommendations(data, repo):
    st.subheader('为你推荐')
    st.caption('研究线索，不是买卖建议。先匹配关注方向，再看已有资料能回答什么。')
    profile = repo.get('user_preferences', 'profile', {})
    if not profile.get('onboarding_completed'):
        empty_state('先选择你的关注方向', '完成上方设置后，推荐理由会与你的选择对应。')
        return
    catalog = remember('industry_catalog', lambda: industry_catalog(data.db))
    rows = recommend(data.db, profile, catalog)
    with st.expander('为什么会看到这些公司？'):
        st.caption('只使用明确行业归属和已保存资料；同一行业先按资料条件、再按代码排序，不做收益评分。各关注行业轮流展示，最多6家公司。')
        st.caption('长期或稳健诉求：同报告期净利润、ROE、经营现金流均为正的资料优先，其次三项齐备，再其次资料不齐。单期为正不等于长期稳健。')
        st.caption('一句话诉求目前只识别“稳健 / 稳定 / 现金流 / 风险”关键词；其他诉求保存供你查看，不由AI猜测。')
        st.caption('中期优先主营与财务齐备；短期优先已有历史走势；“都看看”不加资料优先条件。每次只核对匹配行业中按代码排序的前60家公司，不代表全市场筛选。')
    unmatched = [name for name in profile.get('industries', []) if not catalog['industries'].get(name)]
    if unmatched:st.caption('这些方向暂缺可靠股票归属：'+'、'.join(unmatched)+'。不会猜测或补入公司。')
    if not rows:empty_state('暂时没有可解释的匹配公司', '已有数据不足时保持空白；可在市场浏览可靠行业，或修改偏好。')
    watched = {r['payload']['code'] for r in repo.list('watchlist_items')}
    for row in rows:
        with st.container(border=True):
            research_card(row['name'], row['code']+' · '+row['industry'], row['reason'], '长期观察' if row['period'] == '长期' else '研究线索')
            st.caption('主要风险 / 数据缺口：'+row['risk'])
            quote = row['quote'];change = number(quote.get('change_pct'))
            tone = 'up' if change is not None and change > 0 else 'down' if change is not None and change < 0 else 'neutral'
            metric_grid([('已有价格', fmt(quote.get('price'), ' 元'), '不是实时行情', ''), ('涨跌幅', fmt(change, '%'), '无数据不补值', tone)], columns=2)
            data_meta(row)
            if row['financial_period']:st.caption('财务观察报告期：'+row['financial_period'])
            if row['financial_metadata']:data_meta(row['financial_metadata'])
            if quote:data_meta(row['quote_metadata'])
            st.button('查看研究', key='rec_open_'+row['code'], on_click=open_stock, args=(row['code'],))
            if st.button('已关注' if row['code'] in watched else '加入关注', key='rec_watch_'+row['code'], disabled=row['code'] in watched):
                repo.put('watchlist_items', row['code'], {'code': row['code'], 'name': row['name']});st.rerun()
