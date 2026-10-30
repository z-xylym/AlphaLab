# 公司AI研究 V1

定位：AlphaLab提供事实，DeepSeek负责理解、归纳与有条件的推理。不是开放聊天、实时交易工具或价格预测。

## 数据与边界

`research_context.py` 从现有个股缓存读取基础资料、六项财务摘要、历史日线摘要、主营构成及官方政策索引，不调用实时快照、不接新数据源。`security`、`company_profile`、`financial_summary`、`price_history_summary`、`business_composition`、`policy_context` 均保留来源、日期、抓取时间、missing、cached和stale；另含 missing_data、source_metadata、data_cutoff及版本。

财务保留原始指标名和报告期，缺少经营现金流等指标就明确缺失，不补零、不推算。历史观察使用最多60条已有不复权日线的首末/最低/最高收盘价及最近10条收盘记录，明确不是实时价格或未来收益。主营最多15条，政策最多5条。政策仅为官方索引，不能确认与该公司相关，也不能替代全文政策措施。PE/PB和实时价格明确缺失。

截止日期是各资料实际日期的最大值，不表示全部资料同时更新；报告必须逐项核对报告期。单位未提供时标注未知，不根据数量级换算。

## AI调用与输出

`ai_provider.py` 提供独立DeepSeek HTTP client；Key继续由现有 Settings 从环境变量/Streamlit Secrets 的 DEEPSEEK_API_KEY 读取，只放请求认证头，不存入报告、上下文、hash或日志。HTTPS及TLS验证沿用httpx默认安全行为。连接超时10秒、读取等超时60秒；仅明确429最多重试一次，超时和5xx不自动重试。

沿用 `AI` 服务的服务端身份校验、全局预算锁、个人/平台次数限制和费用预留/结算。失败或不确定结果保留当日预算预留，防止盲目重试重复付费。

`company_report.py` 定义版本化Prompt及固定九章JSON输出。每章单独包含 facts、analysis、missing_data。应用校验章节顺序、字段和类型，格式错误或截断响应不保存为成功报告。Prompt明确禁止模型记忆补全、虚构数字、补缺、无来源估值、买卖建议、目标价及收益保证；财务必须保留报告期。公司报告不读取聊天历史或私人记忆。

**结构校验不是事实核验**。V1不声称能自动验证每个自然语言数字或杜绝幻觉；保存完整必要上下文快照与来源，页面明确提示对照核验。

## 缓存与可审计性

继续使用按用户隔离的 research_reports JSONB，不需要迁移。记录股票代码、生成时间、DeepSeek/model、报告版本、context fingerprint、数据截止日期、结构化九章、兼容研究历史的Markdown正文及完整Context快照。

fingerprint使用规范化JSON与SHA-256，忽略只反映重抓时间的 fetched_at，但保留实际值、报告期、来源、缺失和stale状态。股票与上下文相同就跨日期、跨Streamlit rerun复用；model/报告契约版本也参与报告键。Context实质变化后，用户点击生成取得新报告；不会自动调用API。显式重新生成使用独立请求nonce预留和结算预算，替换同Context的当前报告；历史计费请求仍保留。不共享用户私有报告。

## 页面与上线配置

沿用个股页“AI研究”tab，无新导航。进入页面只读缓存；“生成AI研究”按钮明确触发调用或复用报告；“重新生成AI研究”明确再次计费。报告按九章区分事实、AI分析、数据缺失，底部展示生成时间、截止日期、来源和缺失项，可展开输入快照。失败保留旧报告。未配置Key时友好提示并禁用生成，不影响其他个股页签。

上线前通过安全的部署环境设置配置 DEEPSEEK_API_KEY（不要发到聊天或提交Git）；可设置 DEEPSEEK_MODEL（默认deepseek-chat）及既有预算、调用次数、Token单价。确认部署环境允许 api.deepseek.com。无需修改数据源、初始化管理员或执行数据库迁移。

本轮仅用fake/mock provider、隔离PostgreSQL及UI测试；不调用真实DeepSeek、不产生真实API费用。上线后需使用配置好的服务进行一次低成本报告验收，核对输出九章、来源/报告期、缺失与调用计数。
