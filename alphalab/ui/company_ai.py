"""Existing stock AI tab: explicit calls, durable reports, graceful service failures."""
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from ..config import SetupRequired, UserError
from ..research_context import context_from_cache


def company_ai(view, stock, ai):
    st.subheader('AI研究｜'+stock['name']+' '+stock['code'])
    st.caption('基于 AlphaLab 已保存的真实研究数据生成。')
    context = context_from_cache(view, stock)
    report = ai.saved_company_report(context)
    if not ai.settings.deepseek_api_key:
        st.info('AI研究服务尚未配置')
    with st.expander('本次研究资料与数据缺口'):
        st.json(context)
    generate = st.button('生成AI研究', key='generate_stock_'+stock['code'], type='primary',
                         disabled=not bool(ai.settings.deepseek_api_key))
    regenerate = st.button('重新生成AI研究', key='regenerate_stock_'+stock['code'],
                           disabled=not bool(ai.settings.deepseek_api_key) or not bool(report))
    if regenerate:st.caption('重新生成将再次调用AI，并计入今日额度。')
    if generate or regenerate:
        try:
            with st.spinner('正在生成公司研究…'):
                report, cached = ai.company_report(context, regenerate=regenerate)
            st.caption('已读取已有研究报告。' if cached else '已保存到研究历史。')
        except (SetupRequired, UserError) as exc:
            st.warning(str(exc))
        except Exception:
            st.warning('AI研究暂不可用，请稍后再试；已有报告已保留。')
    if report:
        for section in report['report']['sections']:
            st.subheader(section['title'])
            for key, label in (('facts', '事实'), ('analysis', 'AI分析'), ('missing_data', '数据缺失')):
                if section[key]:
                    st.markdown('**'+label+'**')
                    for line in section[key]:st.markdown(line)
        generated=datetime.fromisoformat(report['created_at']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S 北京时间')
        st.caption('生成时间：'+generated+' · DeepSeek / '+report['model'])
        st.caption('使用的数据截止日期：'+str(report['data_cutoff'] or '缺失')+'；不同资料日期可能不同。')
        st.caption('来源摘要：'+'；'.join(sorted({r['source'] for r in report['context_snapshot']['source_metadata'].values()})))
        st.caption('数据缺失项：'+'、'.join(report['context_snapshot']['missing_data']))
        st.caption(report['audit_note'])
        with st.expander('报告输入快照（可核对来源及报告期）'):
            st.json(report['context_snapshot'])
