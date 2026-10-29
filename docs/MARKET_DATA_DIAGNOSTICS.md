# Streamlit生产公共源诊断与等待时间

适用于Supabase与登录正常，但指数、快照、行业及中国政府网政策同时不可用的情况。本次不修改数据库结构、认证、CA、用户或管理员；只处理公开数据传输、超时、诊断和有限并行读取。

## 先从真实部署机器诊断

开发机器或GitHub Actions的出口IP不同，结果不能替代Streamlit Cloud。合并本PR到main后在Community Cloud **Reboot app**，管理员登录：

**我的 → 管理后台 → 数据源诊断（只读，仅管理员）**。

先运行“域名网络诊断分组”，分别选择：

1. 政府网：www.gov.cn。
2. 东方财富：17/79/82.push2.eastmoney.com（行业/概念/快照）、push2his.eastmoney.com（日线）、push2.eastmoney.com（公司）、emweb.securities.eastmoney.com（主营）。
3. 新浪：vip.stock.finance.sina.com.cn、finance.sina.com.cn、quotes.sina.cn。

每次点击只请求当前固定分组，最多3个并发，结果保留60秒。显示公开host、DNS/TCP/TLS/HTTPS固定类别和各阶段秒数/总秒数；cached=true表示之前测量结果，不是本次重新请求耗时。HTTP只取响应头，不输出URL参数、正文、headers、cookies或证书。参数为空的接口路径HTTP成功只证明传输可达，不能证明实际行情正常。

然后在同一面板选择**单个真实业务接口**运行诊断：

- government_policy_index：中国政府网真实政策索引和当前解析器。
- stock_zh_a_spot_em / stock_zh_a_spot：东方财富与新浪全市场快照。
- stock_zh_index_daily_em：上证指数日线。
- stock_board_industry_name_em / stock_board_concept_name_em：行业与概念。
- stock_zh_a_hist / stock_zh_a_daily：同一公开样本股最近90日历史（各自独立，不让fallback遮住主源失败）。
- stock_individual_info_em、stock_zygc_em：公司资料与主营。
- sina_financial_summary：与生产使用完全相同的新浪财务摘要请求与转换。

显示endpoint、category、elapsed_seconds、cached；单次结果保留30秒，不提供一次性轰击全部接口的按钮。诊断绕过普通调用的失败冷却，便于恢复后复测，但仍受诊断自己的冷却。它不写行情缓存，也不会调用AI。服务端每次重新校验管理员权限；普通用户不会看到内部错误或诊断入口。

没有终端也可以通过页面操作。若平台提供可信终端，也可分别执行：

```text
python -m scripts.diagnose_network 政府网
python -m scripts.diagnose_network 东方财富
python -m scripts.diagnose_network 新浪
python -m scripts.diagnose_market government_policy_index
python -m scripts.diagnose_market stock_board_industry_name_em
```

无需增加任何Secret。只分享固定类别、公开endpoint/host、阶段秒数和cached状态，不分享平台完整日志或网络响应。

## 怎样判断

| 结果 | 可得到的结论 |
|---|---|
| 多个不同域名DNS_ERROR | 优先检查Cloud运行环境DNS/出口配置；不能据此认定密码或AKShare有问题。 |
| DNS成功，TCP NETWORK_ERROR/NETWORK_TIMEOUT | 优先检查出口路由、防火墙、目标侧阻断或服务状态；仅超时无法区分这些原因。 |
| TCP成功，TLS_ERROR | HTTPS证书信任/握手异常；不关闭TLS，不将Supabase专用CA当作所有网站的CA。 |
| HTTP_FORBIDDEN / HTTP_RATE_LIMITED | 目标明确拒绝/限流；停止重试，不伪装登录、轮换代理或绕过安全限制。403本身不能证明地理/云IP限制。 |
| HTTPS CONNECTED，业务PROVIDER_SCHEMA_CHANGED | 返回内容不符合解析要求，可能是接口结构变化，也可能是HTTP200的拦截HTML/验证码；不声称已确认哪一种，不输出正文。 |
| HTTPS CONNECTED，AKSHARE_VERSION_INCOMPATIBLE | 当前安装版本的调用方法/属性不兼容；再核对固定版本与接口签名，不盲目全量升级。 |
| NETWORK_TIMEOUT | 单次请求连接/读取超时。 |
| PROVIDER_TIMEOUT | 12秒总预算耗尽（包括Python/AKShare导入、多页请求、解析）；不能将它单独解释为网络不可达。 |
| AKSHARE_CALL_FAILED / OTHER_ERROR | 当前证据不足以安全细分；保留未知，不打印原异常增加风险。 |
| PROXY_ROUTE | 环境存在代理。直接TCP/TLS预检不执行，HTTPS仍沿平台继承的代理路径；不通过直连绕过平台。DNS直查与代理代解析可能结果不同。 |
| HTTP_REDIRECT | 固定目标返回重定向，诊断不自动追到未知主机；这不等于接口结构正常。 |
| CONNECTED | 本次传输或业务必要字段验证成功，不代表实时性、数据完整性或未来可用率。 |

TLS预检与HTTPS均使用httpx的受支持默认信任配置，保留平台的代理/CA环境。不会输出网络异常原文。即使DNS预检失败，HTTPS仍独立测量，以便代理代解析的环境得到真实结果。

## 慢在哪里，做了什么

已确认的代码问题：旧子进程40秒，东方财富失败后再等新浪40秒；指数/快照/政策在首页依次请求；政策原httpx请求20秒；多用户等公共缓存锁后可能重复失败；setdefault(timeout=15)不能覆盖AKShare传入的timeout=None；AKShare分页工具内部还可能重试与退避。旧异常被吞掉，没有保存HTTP状态，403/429可能被JSON解析错误遮住。

本次：

- 单HTTP请求明确覆盖为连接3秒、读取5秒（读取为不活跃超时，不冒充总墙钟超时）。不保留timeout=None。
- 每个公开provider子进程总预算12秒，强制终止可失控的分页/导入/解析；政府网和新浪财务同样纳入，不只约束AKShare。
- 失败以固定ProviderError向上传递，避免AKShare请求工具再次对403/429等错误自动退避重试；不在本应用额外重试。
- 正常快照/历史仅保留原有一次新浪fallback。必要字段在返回前验证，主源结构错误也能进入既有fallback；不将行业/概念分类混用为“替代数据”。
- 失败按endpoint/公开参数在进程内冷却60秒（最多128个键），刷新不再立刻重打失败源；不改数据库表或写入假失败行情。冷却不跨进程/重启，因此不能当作全平台限流。
- 首页三个独立公共读取最多3线程并行；线程中不调用Streamlit UI。页面显示每类数据读取耗时，某类失败不抹去其他成功结果。
- 原有Supabase公共缓存保留；已有过期缓存且请求失败仍标记stale返回；首次无缓存明确显示不可用、未生成替代数据及冷却提示。

12秒是交互预算，不保证全市场分页能在所有环境完成。快照两源均失败仍可能等待约24秒；首页理论上不再把指数/快照/政策上限串行相加，但数据库连接池/公共锁排队、其他用户竞争等仍可能延长实际等待。成功的三指数读取、个股详情多个区块也是多个请求，不能宣称全页面严格12秒。首页耗时含缓存/上游等待；网络诊断耗时对应阶段。单纯延长总超时会重新拉长卡顿，需结合实测再为特定端点调整。

## 保留、替换与后续选型（本次不实施大改）

- **新浪快照/历史/财务**：保留现有公开备选；必须在Streamlit上单独验证。不能因东方财富失败就假设新浪可用，两个站点也可能都限制云出口。
- **东方财富指数、行业/概念、公司/主营**：暂保留，已有固定版本接口签名可用不代表远端结构未变。只有诊断证明某端点在Cloud持续失败后，再按具体类别修复映射或评估替换。行业没有已验证的同口径备选，当前仍可能不可用。
- **政府网**：保留官方来源。若网络成功而解析失败，应针对官方页面结构修复，不使用未经核实的政策聚合内容冒充原文；若403/429，不能绕过限制。
- **更稳定公开源**：需核对授权、服务条款、数据日期、字段、复权和行业口径。一些较稳定供应商需要付费/凭据，不能直接声称免费替换已完成。暂未新增任何供应商或Key。
- **定时抓取写入Supabase**：已有公共缓存适合后续有权限的定时预热，但GitHub/其他云出口也可能被同样限制；必须先在拟用抓取环境验证且满足源条款。不会改变源端403，也不能保证准实时。
- **后台/预缓存**：比每次用户冷启动全市场抓取更适合长期生产。Community Cloud休眠/重启不保证线程存活，不应把页面内后台线程当可靠定时器。后续可另立任务设计受控调度、成功后原子更新现有缓存、标记日期、失败保留旧数据；本PR未部署调度或写入诊断行情。

## 当前结论与合并后验收

你报告的跨金融源和政府网同时失败，使共同出口/DNS/TLS/访问策略成为首要排查方向；**尚无生产诊断结果，不能把“云IP封禁”当作已证实根因**。错误提示也可能由独立原因同时触发。开发环境网络与Streamlit不同，不能替代实际测量。

合并后Reboot app，先测三个域名组，再逐个测government_policy_index、指数、快照、行业/概念及新浪备选。等待诊断冷却结束再复测，记录固定类别与秒数。回首页确认读取并行、耗时可见、成功源显示真实日期，失败源显示不可用；不要清空历史缓存来试错。普通用户不能运行诊断，任何界面不得显示URL参数、响应正文、cookies、headers或Secrets。

本次开发环境完整回归：**149项测试通过**。测试中的合成HTTP/行情仅存在于测试，未写入生产缓存或作为可用行情展示。没有从用户的Streamlit运行环境取得实测报告，尚未确认其公网HTTPS故障具体类别。
