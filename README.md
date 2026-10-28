# AlphaLab

**让投资研究变得简单。** 面向 A 股初学者的私人研究空间，使用 Streamlit、Supabase PostgreSQL、AKShare 和 DeepSeek。手机优先，不连接券商、不执行真实交易。

本仓库包含可运行的应用、数据库迁移、邀请账户、私人数据持久化、金融数据适配、AI研究、模拟记账与实验回测。**尚未上线；Supabase / DeepSeek 生产凭据未提供，真实金融源在本次云环境被网络策略阻止。不能将自动化夹具测试等同于真实服务验收。**

## 快速启动

Python **3.12**，从仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# 编辑 secrets.toml，填入自己的服务端配置；绝不提交该文件。
python -m scripts.manage migrate
python -m scripts.manage bootstrap
python -m scripts.manage check
streamlit run app.py
```

没有配置时仍可启动，应用明确提示待配置，不显示虚构数据。`bootstrap` 仅手动执行一次；重复执行不会修改已有管理员或重设密码。迁移独立于页面刷新；禁止将迁移命令塞进 `app.py`。

配置也可通过同名环境变量提供，环境变量优先；应用不自动加载 `.env`。数据库必须是 PostgreSQL。远程连接强制校验证书 `sslmode=verify-full`；生产数据不写本地文件，不支持 SQLite 替代。`APP_SECRET_KEY` 至少32随机字符，用 `python -c "import secrets; print(secrets.token_hex(32))"` 在你自己的安全终端生成。

**已用Supabase SQL Editor建好表、希望不用安装Python？** 请按 [GitHub网页初始化管理员](docs/ADMIN_BOOTSTRAP.md) 操作。真实密码仅填GitHub加密Secrets，工作流只检查现有库并创建首位管理员。

管理员初始化后：登录 → 我的 → 管理后台 → 指定手机号生成邀请码 → 受邀人通过邀请码设置12～128字符密码。邀请码3天有效，仅显示一次。手机号并未短信验证，不能代表号码所有权；丢失密码需可信管理员另行安全处理，V1不提供短信找回。

## 功能入口

- **首页**：最近发布的指数日线、A股快照、官方政策索引、手动生成市场简报。
- **行业**：东方财富行业口径与投资主题分开选择；成分股、关注行业、AI解释和官方原文分析。
- **选股**：风险警示、上市时间、流动性、数据完整性过滤；低估值、质量、实验短期动量；结果长期保存。
- **个股**：名称/代码/关键词搜索、公司资料、主营构成、不复权历史图、财务摘要、PE/PB、研究报告和自选。
- **我的**：手动持仓增改删和集中度、聊天和长期记忆、报告检索删除、历史名单观察收益、模拟账本、回测、偏好和密码、管理员额度/用户/缓存管理。

AI仅在明确点击生成或发送聊天时调用。已完成的相同研究请求按用户、材料、模型、日期去重；原始材料变化会产生新报告。聊天每次发送算独立请求。超时不盲目重试，防止重复费用。AI事实约束通过系统提示和有来源上下文实现，**不能保证模型不会幻觉，使用者仍需核验输出**。

费用为人民币估算：实际输入/输出 Token × 配置的每百万 Token 单价。模板单价仅为配置示例，不保证对应当前官方价格。调用前在 PostgreSQL 全局锁下预留最大预算，同时检查个人次数、平台次数和日预算；未知结果保留当日预留。平台每日预算和次数通过 Secrets 配置，管理员后台可调整普通用户个人额度。重试只针对一次明确429拒绝；超时、5xx不自动重复发送。每日额度按北京时间重置。

## 测试与证据

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.probe              # 只读真实源检查；需要允许的域名
python -m scripts.browser_check      # 可选：需要 /usr/bin/chromium
```

测试默认通过 `pgserver` 启动一次性 PostgreSQL，不连接 Supabase，不使用 SQLite。也可传入**专用可销毁的** `TEST_DATABASE_URL`；测试会清空其中应用表，绝不能指向生产数据库。测试账号和合成行情仅存在于 tests / 临时测试数据库，不进入应用或公共缓存。

测试范围、结果、截图和未验证项见 [验收记录](docs/VALIDATION.md)。部署步骤见 [部署说明](docs/DEPLOYMENT.md)，架构与安全边界见 [架构说明](docs/ARCHITECTURE.md)，范围限制见 [当前限制](docs/LIMITATIONS.md)。

## 目录

```text
app.py                     Streamlit入口
alphalab/config.py         Secrets/环境变量配置与待配置状态
alphalab/db.py             PostgreSQL表、连接池与事务锁
alphalab/auth.py           Argon2id、邀请、会话、频控、管理员初始化
alphalab/repository.py     服务端身份验证、按用户作用域访问、记忆检索
alphalab/data.py           公共数据缓存、行情/公司/财务/行业/官方政策
alphalab/provider.py       有界AKShare子进程，防上游挂起
alphalab/ai.py             DeepSeek、事实约束、幂等、预算预留与用量
alphalab/research.py       统一筛选阈值、持仓指标、名单观察收益
alphalab/trading.py        模拟账本、T+1、实验性均线回测
alphalab/ui.py             五入口及私人/管理员页面
assets/styles.css         移动端样式
scripts/manage.py         幂等迁移/初始化/连通检查
scripts/probe.py           只读外部源诊断
scripts/browser_check.py   手机视口集成检查
scripts/export_schema.py   从模型导出SQL
database/migrations/001_initial.sql
tests/                    pytest自动化检查
docs/                     部署、架构、验收与限制
```

## 使用边界

公开金融接口可能失效、延迟或受地区/云IP限制，来源标记和抓取时间不能当作交易日期。首次源失败显示不可用，有旧缓存则清楚标记过时。回测和模拟为研究用途，未实现真实交易所撮合、所有历史规则与公司行为调整；不应据此推断可实现收益或承诺“稳定盈利”。
