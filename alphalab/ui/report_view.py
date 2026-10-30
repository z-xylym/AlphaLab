"""Shared report reader; no generation, billing or context changes."""
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from .components import planned_panel, metric_grid


def render_report(report):
    st.caption('已保存报告 · 事实与分析分开阅读，关键数字请核对来源和报告期。')
    metric_grid([('数据截止', str(report.get('data_cutoff') or '缺失'), '不同资料日期可能不同', ''),
                 ('报告模型', report['model'], 'DeepSeek · 已保存', ''),
                 ('数据缺口', str(len(report['context_snapshot']['missing_data'])), '保留缺失，不替你补全事实', '')])
    with st.container(key='ai_report'):
        for index, section in enumerate(report['report']['sections'], 1):
            with st.container(border=True):
                st.caption(f'{index:02d} / 09 · COMPANY RESEARCH')
                st.subheader(section['title'])
                for key, label in (('facts', '事实'), ('analysis', 'AI分析'), ('missing_data', '数据缺失')):
                    if section[key]:
                        st.markdown('**'+label+'**')
                        for line in section[key]:st.markdown(line)
    generated = datetime.fromisoformat(report['created_at']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S 北京时间')
    st.caption('生成时间：'+generated+' · DeepSeek / '+report['model'])
    st.caption('使用的数据截止日期：'+str(report.get('data_cutoff') or '缺失')+'；不同资料日期可能不同。')
    with st.expander('数据来源与缺失项', expanded=False):
        st.caption('来源摘要：'+'；'.join(sorted({r['source'] for r in report['context_snapshot']['source_metadata'].values()})))
        st.caption('数据缺失项：'+'、'.join(report['context_snapshot']['missing_data']))
        st.caption(report['audit_note'])
    with st.expander('报告输入快照（可核对来源及报告期）'):
        st.json(report['context_snapshot'])


def followup_placeholder(key):
    with st.expander('继续追问 · 研究问答', expanded=False):
        st.caption('规划中 · 尚未接通，不会发送问题或产生AI费用。')
        st.text_area('围绕本报告继续研究', placeholder='未来可就财务变化、风险条件或政策关联继续追问', disabled=True, key='planned_followup_'+key)
        planned_panel('对话记录', '后续研究问答将在这里独立呈现，不混入公司事实或原始报告。')
