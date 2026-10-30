import pandas as pd
import streamlit as st
from ..data import DataUnavailable
from .reads import invalidate

def admin_security_master(data,repo):
    # Also check the current server-side role when this block is called directly.
    with repo.db.begin() as conn:
        repo.auth.principal(conn,repo.token,admin=True)
    st.subheader('基础证券名单')
    st.caption('独立交易所公开名单，不依赖全市场实时快照；仅更新公共缓存，不包含实时价格。原刷新按钮仅刷新沪深，北交所需单独刷新；部分交易所成功不代表全市场覆盖。')
    result=None
    refresh_main=st.button('更新基础证券名单',key='admin_refresh_security_master')
    refresh_bj=st.button('单独更新北交所名单（最长45秒）',key='admin_refresh_security_master_bj')
    if refresh_main or refresh_bj:
        # Reauthorize immediately before requesting or writing public data.
        with repo.db.begin() as conn:
            repo.auth.principal(conn,repo.token,admin=True)
        try:
            with st.spinner('读取交易所公开名单并保存公共缓存，失败时保留旧名单…'):
                result=data.security_master(exchange='BJ' if refresh_bj else ('SH','SZ'),refresh=True)
            invalidate()
            fresh=[x for x in result['items'] if not x['stale']]
            if fresh:
                sources='、'.join(sorted({x['source'] for x in fresh}))
                fetched=min(x['fetched_at'] for x in fresh)
                st.success(f"更新成功 · 本次更新股票数量：{len(fresh)} · 来源：{sources} · 数据时间（抓取时间）：{fetched}")
                if result['stale']:
                    st.warning('部分交易所更新失败，已保留旧名单；请查看下方各来源状态。')
            else:
                st.error('基础证券名单更新失败，已有旧缓存已保留。请使用只读数据源诊断后重试。')
        except Exception:
            # Never render/log provider exceptions, URLs, response bodies or secrets.
            st.error('基础证券名单更新失败，已有旧缓存已保留。请使用只读数据源诊断后重试。')
    if result is None:
        try:
            # Opening the admin page must not implicitly fetch external sources.
            result=data.security_master(cached_only=True)
        except DataUnavailable:
            st.info('是否已有缓存：否 · 股票数量：0 · 来源：暂无 · 抓取时间：暂无 · stale：不适用。')
            return
        except Exception:
            st.error('基础证券名单状态暂不可读取，未清除已有缓存。请稍后重试。')
            return
    if refresh_main or refresh_bj:
        try:
            saved=data.security_master(cached_only=True)
            refreshed={'BJ'} if refresh_bj else {'SH','SZ'}
            result=dict(result,items=[x for x in result['items'] if x['exchange'] in refreshed]+[x for x in saved['items'] if x['exchange'] not in refreshed])
        except DataUnavailable:pass
    st.write('是否已有缓存：是')
    st.metric('股票数量',len(result['items']))
    groups={}
    for item in result['items']:
        key=(item['exchange'],item['source'],item['fetched_at'],bool(item['stale']))
        groups[key]=groups.get(key,0)+1
    st.dataframe(pd.DataFrame([
        {'交易所':ex,'股票数量':count,'来源':src,'抓取时间':fetched,'stale':stale}
        for (ex,src,fetched,stale),count in sorted(groups.items())
    ]),hide_index=True,use_container_width=True)
    if result['stale']:
        st.warning('部分名单为历史缓存（stale），来源与原抓取时间保持不变。')

def admin(data,repo,auth):
    # Every admin method performs fresh server-side authorization.
    users=repo.admin_users()
    st.subheader('管理后台')
    admin_security_master(data,repo)
    with st.expander('数据源诊断（只读，仅管理员）'):
        from ..market_diagnostics import PROBES, probe_report_for_admin
        from ..network_diagnostics import GROUPS, report_for_admin
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
    if st.button('清除公共数据缓存',key='danger_clear_public_cache'):
        repo.clear_cache();invalidate();st.success('已清除，私人数据不受影响。')
