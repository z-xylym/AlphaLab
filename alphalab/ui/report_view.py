"""Shared report reader; no generation, billing or context changes."""
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from .components import metric_grid


def render_report(report, key='ai_report'):
    st.caption('已保存报告 · 事实与分析分开阅读，关键数字请核对来源和报告期。')
    metric_grid([('数据截止', str(report.get('data_cutoff') or '缺失'), '不同资料日期可能不同', ''),
                 ('报告模型', report['model'], 'DeepSeek · 已保存', ''),
                 ('数据缺口', str(len(report['context_snapshot']['missing_data'])), '保留缺失，不替你补全事实', '')])
    with st.container(key=key):
        summary = report.get('report', {}).get('summary')
        if summary:
            st.subheader('精简研究摘要')
            labels = {'opinion': '当前观点', 'judgment': '核心判断', 'facts': '关键事实',
                      'short_term': '短期观察', 'medium_term': '中期经营', 'long_term': '长期逻辑',
                      'holding_advice': '已持有建议', 'not_holding_advice': '未持有建议',
                      'risks': '主要风险', 'change_conditions': '判断改变条件'}
            if isinstance(summary, dict):
                for key, value in summary.items():
                    st.markdown('**'+labels.get(key, key)+'**')
                    if isinstance(value, list):
                        for line in value:st.markdown('- '+str(line))
                    else:st.write(value)
            else:st.write(summary)
        with st.container():
            for index, section in enumerate(report['report'].get('sections', []), 1):
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


def stock_followup(ai, context, key):
    from ..config import SetupRequired, UserError
    code = context['security']['code']['value']
    with st.expander('继续问 AlphaLab', expanded=False):
        st.caption('只在发送时调用AI；按当前股票保存，最多保留4轮有界问答。')
        turns = ai.stock_history(code)
        for turn in turns:
            with st.chat_message('user'):st.write(turn['question'])
            with st.chat_message('assistant'):st.write(turn['answer'])
        with st.form('followup_'+key, clear_on_submit=True):
            question = st.text_area('围绕本报告继续研究', max_chars=1000, key='question_'+key,
                                    disabled=not bool(ai.settings.deepseek_api_key))
            send = st.form_submit_button('发送问题', disabled=not bool(ai.settings.deepseek_api_key))
        if send:
            try:
                with st.spinner('AlphaLab 正在研究你的问题…'):
                    answer = ai.stock_followup(context, question)
                with st.chat_message('user'):st.write(question)
                with st.chat_message('assistant'):st.write(answer)
            except (SetupRequired, UserError) as exc:st.warning(str(exc))
            except Exception:st.warning('研究问答暂不可用；原报告和已有问答已保留。')
