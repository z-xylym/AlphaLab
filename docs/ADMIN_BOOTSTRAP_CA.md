# 显式CA验证已成功后：初始化管理员

适用于你已经在 **Verify Supabase CA connection (read only)** 得到CONNECTED的情况。无需修改数据库密码、DATABASE_URL或其他现有Secrets。

## 修复内容

以前只有独立验证工作流使用显式CA，管理员工作流的诊断与manage命令仍使用原始URL，可能再次依赖system失败。本次修复让：

1. 只读诊断注入SUPABASE_CA_CERT，运行 `python -m scripts.diagnose_database --explicit-ca`。
2. 初始化步骤运行 `python -m scripts.bootstrap_with_ca`。包装器调用已有 `explicit_ca_url()`，在一个CA上下文内，依次启动check、bootstrap、admin-check三个子进程。
3. 三个子进程得到相同的显式CA URL，CA文件直到三个命令结束才清理。仓库公有CA保留，只有Secret生成的临时文件被删除。

包装器仅在子进程环境中覆盖DATABASE_URL，不修改GitHub Secret或父进程环境，不写GITHUB_ENV、文件或日志中的URL。没有另一套TLS实现，也没有system回退。保持Session pooler、5432、SQLAlchemy/psycopg和verify-full不变。诊断与管理两个步骤各自建立CA上下文，使用同一来源的CA内容；三条管理命令共享同一个文件和上下文。

## 合并后怎样运行

1. 确认本PR已合并到 **main**。
2. 保留已验证成功的 **DATABASE_URL** 和 **SUPABASE_CA_CERT** Secrets，以及已有 **APP_SECRET_KEY、ADMIN_PHONE、ADMIN_INITIAL_PASSWORD**。不重填、不重新编码、不更换数据库密码。
3. 打开 **Actions → Initialize first administrator → Run workflow**。
4. Branch选择 **main**，confirmation填 **INITIALIZE**，点击 **Run workflow**。
5. 打开本次新的运行记录，先看 **Diagnose database connection (read only)**，再看 **Check existing schema and initialize administrator**。

不要点击旧失败记录的Re-run jobs，旧运行可能仍使用旧提交。不要运行migrate或重跑001_initial.sql。

如果希望先验证工作流接线，可先选 **DIAGNOSE**：该模式仍只读，管理步骤会跳过；之后再新建一次运行，填INITIALIZE。

## 成功日志

只读诊断应显示：

```text
DIAGNOSIS: CONNECTED
```

管理步骤应依次显示：

```text
Database schema v1 reachable.
Admin created.
Admin ready: enabled account with Argon2id password hash. No credentials displayed.
Bootstrap chain completed with explicit CA. Temporary certificate context closed.
```

已有管理员时第二行是：

```text
Admin already exists; unchanged.
```

不会重设密码、再建一个管理员、提升同号普通用户权限或修改已有用户。管理员bootstrap本身的事务锁与幂等逻辑未修改。

## 安全失败

- CA缺失/无效：TLS_CA_CONFIGURATION_ERROR，管理命令不执行。
- check失败：不执行bootstrap与admin-check。
- bootstrap失败：不执行admin-check。
- 子进程超时、输出异常或失败：只显示固定失败阶段或通用类别，原始stdout/stderr全部抑制，不转发可能包含URL、证书或Secrets的输出。
- 中途停止后，CA上下文仍会退出清理临时文件。若bootstrap已经成功而后续admin-check失败，**不撤销或重建账户**；查明故障后再运行，已有管理员会跳过。

工作流只调用check/bootstrap/admin-check，不建库、不迁移、不清表。应用的登录和管理员逻辑没有改动。Secrets不会自动同步到Streamlit，管理员确认成功后的部署另按DEPLOYMENT.md操作；不应将临时runner路径复制到Streamlit配置。

## 测试边界

新增测试验证workflow的两个步骤均注入CA、显式诊断参数、三条子命令顺序与同一CA上下文、父URL不变、失败即停、CA错误不启动子进程、既有管理员跳过日志，以及子进程输出/异常可能包含Secrets时也不泄漏。此前真实psycopg/libpq证书链和主机名验证及PostgreSQL幂等初始化测试继续保留。

本次开发没有连接你的生产Supabase，也没有替你运行INITIALIZE；成功以新的Actions运行日志及随后实际登录为准。

本次完整回归：**106项测试通过**。
