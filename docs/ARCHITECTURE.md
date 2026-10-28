# 架构与安全边界

Streamlit 浏览器只持有当前会话的界面状态。服务器Session State保存随机会话令牌，数据库仅保存 HMAC-SHA256 摘要及到期时间。每次私人读写、每次管理员操作都重新从数据库解析令牌、用户启用状态和角色；不能传入user_id来切换身份。退出、禁用、修改密码都会吊销会话。页面URL不承载身份。WebSocket断开/浏览器刷新可能丢失Session State，重新登录即可找回长期数据。

手机号唯一，内部UUID独立。密码为Argon2id，12～128字符；后台不会返回哈希。登录失败按手机号HMAC和平台总量在数据库事务锁下限制，15分钟5次/平台100次；因为无可信客户端IP，不伪造IP级防护。用户不存在时仍执行Argon2验证以减小时序差。邀请是高熵随机码，保存摘要，限手机号、3天、一次消费，并发消费串行化。V1没有手机号归属校验、短信找回或MFA。

私人文档表都有 `user_id` 外键和 `(user_id,key)` 唯一索引。服务层不接受来自页面的owner字段。持仓、聊天、报告、记忆分别属于各自用户。管理员仅可读用户状态/额度和调用计量，不提供查看其他人私人内容的接口。管理员后台手机号掩码；管理方法本身也重新检查角色，隐藏按钮并不是授权机制。

RLS在迁移时对所有应用表启用且不创建匿名策略，阻止Supabase REST匿名端读取。后端使用数据库owner连接，**owner能绕过RLS**，本应用按用户隔离由认证Repository和服务层强制保证，不宣称数据库owner下仍有自动user_id行隔离。不要给浏览器service role、数据库密码或后端密钥。若威胁模型要求数据库层多租户强隔离，需要独立应用角色、事务级已认证身份与FORCE RLS的后续迁移及专项审计。

## 数据库

- 账户：users、invitations、auth_sessions、login_attempts。
- 私人：user_preferences、chat_sessions、chat_messages、user_memories、research_reports、watchlists、watchlist_items、portfolios、portfolio_positions、simulated_trades、screening_runs、strategy_results。
- 公共：stock_master、stock_prices、industries、industry_members、policies、policy_industries、public_cache。
- 审计计量：api_usage_logs；版本：schema_migrations。

私人领域对象以带UUID/owner/key/时间索引的JSONB文档存储，交易账本由账户锁保护；不是把整个数据库塞到一个JSON文件。公共数据的权威读取路径是 `public_cache`；部分专用公共目录表用于索引扩展，尚不将所有行情逐行复制或把AI推测自动写成确定的政策关系。

迁移只有命令行管理程序执行。v1 SQL由 `python -m scripts.export_schema` 导出；可选SQL Editor仅用于空库首次初始化。后续新增升级须新增有序迁移版本，在事务锁下执行、记录schema_migrations并在测试库验证回滚/兼容。`create_all` 不能自动迁移已存在字段，禁止把它当作未来升级方案。升级前从Supabase导出备份并核验恢复；回退应用不等于删除新增表。

## 公共数据和缓存

行情180秒；指数900秒；行业/成分1800秒；历史/政策3600秒；财务21600秒；公司资料/主营/官方正文86400秒。不同用户共享公共缓存；跨进程PostgreSQL advisory事务锁避免重复请求；上游失败不删除缓存。缓存来源、抓取时间、stale状态全部返回，接口不提供交易日期时不编造。AKShare在有界子进程中运行，单调用最多40秒，失败可尝试已实现的备选；没有有效历史数据则不可用。

政策索引只采中国政府网，HTTPS原文链接限制同一官方域名、禁止跟随任意重定向、限制2MB正文。标题和索引不等于已验证全文；AI只能基于抓取到的原文解释。未识别发布状态保留“待核对”，不擅自判定正式生效。AI公司关联是分析推断，不自动成为已核实的事实关系。

## AI 与资金控制

个人/平台次数和预算在全局事务锁下原子检查与预留，网络请求在预留提交后进行；中断产生unknown状态，保留预算至当天结束。相同研究去重键不包含变化的历史记忆，防止生成报告后自身记忆破坏去重；用户、日期、材料和模型不同则不共享私人报告。重复请求pending/unknown会拒绝再次调用。

实际Token按配置单价计算，记录到使用日志。报告和聊天持久化到各自owner行。上下文只取有限相关记忆和最近对话，并保留历史日期；不发送全部用户历史。提示约束降低幻觉风险但不提供事实正确性的数学保证。所有外部请求、SQL异常在产品界面做通用错误处理，不回显URL、headers或SQL参数。

不实现券商、资金转账或真实订单API。模拟交易使用最近日线作教育记账，不自称真实撮合。实验回测仅使用昨日收盘信号到次日开盘，不接入未核对公告日的历史财务指标。
