# 部署到 Streamlit Community Cloud

无需自有服务器。需要你拥有 GitHub 私有仓库、Streamlit Community Cloud 和 Supabase 项目访问权。此文档不代表应用已上线，也未替你创建或付费订阅任何服务。

## 1. GitHub

将代码提交到你控制的 **z-xylym/AlphaLab** 私有仓库。先检查 `git status` 和变更，排除 `.streamlit/secrets.toml`、`.env`、测试数据库、日志和手机截图。`.gitignore` 已排除相关文件。部署入口是仓库根目录 `app.py`。用户在 GitHub 和 Community Cloud 中自行授予私有仓库读取授权；不需要把 GitHub Token 放入应用。

## 2. 创建 Supabase PostgreSQL

1. 创建 Supabase 项目并安全保存数据库密码。应用通过 SQLAlchemy/psycopg 从服务端连接，不使用浏览器 Supabase SDK。
2. 在项目 Connect 面板复制 **Session pooler** 连接信息。Community Cloud 出网可能仅支持 IPv4，优先选择支持 IPv4 的 session pooler；应用已有小型连接池（3+2），避免大量连接。不要假设直连 IPv6一定可用。
3. 构造 `postgresql+psycopg://用户名:URL编码密码@主机:5432/postgres?sslmode=verify-full&sslrootcert=system`。用户名可能是 `postgres.PROJECT`，以你的项目面板为准。密码里的 `@:/?#%` 等必须进行 URL 编码。
4. 保留 TLS 证书验证。如果系统 CA 无法验证 Supabase 证书，从 Supabase 官方项目面板获取对应根 CA，放入部署仓库的 `certs/`（公有 CA 证书不是密钥），将 `sslrootcert` 改为文件绝对路径。**不要改成 disable、不用 verify=False，也不通过跳过证书校验解决问题。**
5. 最简部署使用项目数据库 owner 作为服务端连接角色，仅保存在 Secrets，不暴露给浏览器。上线规模扩大时，应建立独立受限的应用角色/迁移角色并专项审计授权。当前服务端私有隔离由 Repository 强制实现；RLS无浏览器授权策略，阻止 anon/authenticated直接读表。不能将匿名角色用作本应用数据库角色。

## 3. 初始化数据库和首位管理员

**不安装本地Python的推荐方案：** 已通过SQL Editor完成初始化的用户，请按 [GitHub网页一键初始化管理员](ADMIN_BOOTSTRAP.md) 操作。该工作流只检查现有版本并初始化首位管理员，不执行迁移或清表。下方命令行方案仍可用于开发者。

在你可信的本地终端或已获准连接数据库的开发环境中：

```bash
# 按README安装依赖，编辑真实 .streamlit/secrets.toml 后
python -m scripts.manage migrate
python -m scripts.manage bootstrap
python -m scripts.manage check
```

这只是运行一次性管理命令，不要求你运行长期服务器。迁移按 `schema_migrations.version` 幂等执行；bootstrap固定使用 Secrets 中的管理员配置，已有管理员时无操作。不要每次页面运行都执行这些命令。

也可在 Supabase SQL Editor 执行 `database/migrations/001_initial.sql`（仅空数据库首次初始化；有数据升级使用 manage 和新增版本迁移）。该SQL没有管理员明文密码，不创建管理员账户；仍需在可信终端执行 `bootstrap`，确保 Argon2id 哈希由应用生成。不要在SQL Editor保存管理员明文密码。

初始化成功后，可以从生产 Secrets 移除 `ADMIN_INITIAL_PASSWORD`（不要移除 APP_SECRET_KEY）。它不会用作登录后门、找回密码或每次刷新重设密码。管理员可以登录后通过个人设置修改密码，此操作吊销所有会话。切勿将模板密码用于生产。

## 4. Community Cloud

1. 使用 Streamlit Community Cloud 的 New app，从你的私有仓库选择部署分支。
2. Main file path 选 `app.py`，Python 选 **3.12**，依赖由根目录 `requirements.txt` 安装。
3. 在 Advanced settings / Secrets 填入 `.streamlit/secrets.toml.example` 的内容，并替换为真实值。不要把真实内容粘贴到聊天或提交GitHub。
4. 填写 DATABASE_URL、APP_SECRET_KEY、DEEPSEEK_API_KEY 和模型；核对当时官方 Token 单价和允许的日预算。DeepSeek Key由管理员提供，普通用户无需配置。
5. 部署应用，检查日志中是否有依赖安装失败，不应输出 Secrets。必要时重启应用刷新配置。所有长期数据位于Supabase，Community Cloud休眠/重启不会丢失这些记录；浏览器会话可能失效，需要重新登录。
6. 用你发布后的实际公网网址完成以下验收；本仓库未生成或声称已有公网地址。

## 5. 上线验收

- 用首位管理员登录，创建指定手机号邀请；注册普通用户。
- 两个浏览器会话分别登录，保存不同自选、聊天、报告和持仓，再退出重新登录确认持久化。
- 确认普通用户看不到管理入口，禁用普通用户后原会话立即被拒绝。
- 检查首页指数日线实际日期与来源；快照未提供可信交易日期时保持提示。
- 名称、简称、代码搜索；检查财务报表日期、主营构成，缺字段应显示暂无可靠数据。
- 打开官方政策原文，核对发文部门、发布时间、征求意见/生效状态。AI关联必须当推断看待。
- 只生成一次DeepSeek报告，重复点击相同材料应返回缓存；观察用量与估价；把额度设为0后确认被阻止。
- 尝试T+1当天卖出和资金不足的模拟订单，确认拒绝；检查回测的样本外、成本和限制标签。
- 在真实375/390/430px手机浏览器检查图表、长报告、输入法和导航；开发测试未代替真机验收。

## 6. 常见故障

| 现象 | 处理 |
|---|---|
| 数据库连接失败 | 确认pooler主机、端口、项目状态、用户名和密码编码；使用管理命令check，核对CA。不要公开完整URL。 |
| TLS错误 | 使用Supabase官方根CA/受支持信任链；不得关闭验证。 |
| 休眠后无法登录 | 检查Supabase项目是否暂停、数据库是否迁移、APP_SECRET_KEY是否被改变。 |
| 管理员未创建 | 在可信终端执行bootstrap；不靠刷新页面初始化。 |
| AKShare失败 | 查看来源状态；云IP/地区/接口变化可能导致失败。旧缓存会标记过时；不要以测试夹具替代真实行情。 |
| 全市场数据加载慢 | 上游有分页与限速，单接口40秒上限；等待或使用历史缓存，不增加并发轰击数据源。 |
| DeepSeek失败 | 检查Key、官方服务余额、网络、模型及个人/平台预算。超时保留预留，避免再次计费。 |
| 达到预算 | 用量记录中的unknown保守预留到北京时间次日；核对官方账单再调整配置。 |
| RLS导致服务端拒绝 | 连接角色需拥有后端访问能力；不要为anon添加全表允许策略来修复。 |
| 重启后聊天消失 | 确认相同Supabase与相同用户登录，检查是否误删除；不应切换临时测试数据库。 |

## 7. 本次 Codex 云环境的网络设置

当前代码开发环境与最终 Community Cloud 是两个不同平台。Codex 环境已保存安装/启动说明和以下自定义域名草稿：`api.deepseek.com`、`www.gov.cn`、`push2.eastmoney.com`、`82.push2.eastmoney.com`、`17.push2.eastmoney.com`、`29.push2.eastmoney.com`、`79.push2.eastmoney.com`、`push2his.eastmoney.com`、`finance.sina.com.cn`、`vip.stock.finance.sina.com.cn`、`quotes.sina.cn`、`emweb.securities.eastmoney.com`。需要在环境设置中查看并保存变更，然后发布环境；保存草稿并不会即时应用或发布。

Supabase是数据库TCP连接，不能靠只添加HTTP域名就假定已能访问。如果要从此开发环境连接，需平台支持的目标主机/端口授权和真实凭据；这些尚未配置。Community Cloud则在其自身Secrets和网络环境中单独验证。
