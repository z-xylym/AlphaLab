"""Existing stock AI tab: explicit calls, durable reports, graceful service failures."""
import streamlit as st
from ..config import SetupRequired, UserError
from ..research_context import context_from_cache


def company_ai(view, stock, ai):
    st.subheader('AI研究｜'+stock['name']+' '+stock['code'])
    st.caption('基于 AlphaLab 已保存的真实研究数据生成。')
    context = context_from_cache(view, stock)
    report = ai.saved_company_summary(context) or ai.saved_company_report(context) or ai.repo.latest_company_report(stock['code'])
    if not ai.settings.deepseek_api_key:
        st.info('AI研究服务尚未配置')
    with st.expander('本次研究资料与数据缺口'):
        st.json(context)
    actions=st.columns(2)
    with actions[0]:
        generate = st.button('生成AI研究', key='generate_stock_'+stock['code'], type='primary',
                         disabled=not bool(ai.settings.deepseek_api_key))
    with actions[1]:
        regenerate = st.button('重新生成AI研究', key='regenerate_stock_'+stock['code'],
                           disabled=not bool(ai.settings.deepseek_api_key) or not bool(report))
    if regenerate:st.caption('重新生成将再次调用AI，并计入今日额度。')
    if generate or regenerate:
        try:
            with st.spinner('正在生成公司研究…'):
                report, cached = ai.company_summary(context, regenerate=regenerate)
            st.caption('已读取已有研究报告。' if cached else '已保存到研究历史。')
        except (SetupRequired, UserError) as exc:
            st.warning(str(exc))
        except Exception:
            st.warning('AI研究暂不可用，请稍后再试；已有报告已保留。')
    from ..research_context import fingerprint
    from .report_view import render_report, stock_followup
    if report:
        if report.get('context_fingerprint') != fingerprint(context):
            st.caption('这份研究对应较早数据；生成AI研究可基于当前资料更新摘要。')
        render_report(report)
    full = ai.saved_company_report(context)
    if not full:
        full = ai.repo.latest_company_report(stock['code'], kind='full')
    if st.button('生成完整研究依据', key='generate_full_'+stock['code'],
                 disabled=not bool(ai.settings.deepseek_api_key)):
        try:
            with st.spinner('正在生成完整研究依据…'):
                full, cached = ai.company_report(context)
            st.caption('已复用相同资料的完整研究依据。' if cached else '完整研究依据已保存。')
        except (SetupRequired, UserError) as exc:st.warning(str(exc))
        except Exception:st.warning('完整研究依据暂不可用；旧报告已保留。')
    if full and full != report:
        with st.expander('完整研究依据', expanded=False):
            if full.get('context_fingerprint') != fingerprint(context):
                st.caption('这份完整研究依据对应较早数据，请核对资料日期。')
            render_report(full, key='ai_full_report')
    stock_followup(ai, context, 'stock_'+stock['code'])
