# 不安装Python：用GitHub网页初始化首位管理员

你已在Supabase SQL Editor成功执行完整 `001_initial.sql`，接下来**不必重新建库、清表或重跑迁移**。推荐先用GitHub Actions运行一次性命令，再部署Community Cloud。整个过程只需要浏览器，不需要自己的服务器，也不需要把密码发给Codex。

## 先合并本次更新

将包含 `.github/workflows/bootstrap-admin.yml` 的PR合并到 **main**。手动工作流只有进入默认分支后才会出现在Actions页面。不要使用别人未经审核的分支运行生产Secrets。

## 1. 在GitHub保存一次性初始化Secrets

打开 **z-xylym/AlphaLab → Settings → Secrets and variables → Actions**。

在 **Repository secrets** 区域点击 **New repository secret**，分别添加下列四项。每项的Name填左列，Secret填你自己的真实内容，点击 **Add secret** 保存；不要放入普通Variables、workflow输入框、Issue、PR描述或聊天。

这里使用仓库Actions Secrets，不依赖某些私有仓库套餐才支持的GitHub Environments功能。工作流本身检查运行分支必须为main，且仅手动触发。

| Name | Secret填写什么 |
|---|---|
| `DATABASE_URL` | 你的Supabase PostgreSQL连接URL，含密码。推荐Connect面板的IPv4 **Session pooler**，以 `postgresql+psycopg://` 开头，保留 `sslmode=verify-full&sslrootcert=system`。 |
| `APP_SECRET_KEY` | 密码管理器生成的至少32字符随机字符串（建议64字符字母数字）。部署Streamlit时使用同一个值，不使用模板占位符。 |
| `ADMIN_PHONE` | 首位管理员真实中国大陆手机号，作为登录标识。 |
| `ADMIN_INITIAL_PASSWORD` | 密码管理器生成的独立强密码，12～128字符；以后用这个密码登录。 |

**无需添加DeepSeek Key**，初始化不调用AI。不要将真实 `.env` 或 `secrets.toml` 上传GitHub。这里的Secrets是GitHub加密配置，不是仓库文件；有权修改工作流的人仍可能读取它们，因此只信任你控制的main代码。

连接URL形状示例（全部是占位符）：

```text
postgresql+psycopg://postgres.PROJECT:URL_ENCODED_PASSWORD@aws-REGION.pooler.supabase.com:5432/postgres?sslmode=verify-full&sslrootcert=system
```

以Supabase **Connect** 页实际提供的用户名、主机和端口为准，不照抄示例。密码含 `@ : / ? # % &` 等字符时必须进行URL编码；只在你自己的可信工具中处理，不把密码交给在线编码网站。如果原本密码很难处理，可以在Supabase管理界面设置新的长随机字母数字数据库密码，并同步所有使用它的配置（会影响其他连接）。

若系统信任链无法验证数据库证书，从Supabase官方项目面板下载正确的根CA，作为公有证书放入仓库 `certs/supabase-root.crt`，将URL参数改成 `sslrootcert=certs/supabase-root.crt`，然后重试。只可提交公有CA证书，**不得提交私钥或数据库密码**。不能通过关闭TLS验证解决失败。

## 2. 点击运行（只在GitHub上运行）

仓库顶部 **Actions → Initialize first administrator → Run workflow**：

1. Branch选 **main**。
2. confirmation填写 **INITIALIZE**，这里仅是确认词，不填任何密码。
3. 点击绿色 **Run workflow**。
4. 打开新出现的运行记录，再点击 `bootstrap` 任务。

GitHub托管的临时Ubuntu机器会自动安装Python 3.12和依赖，再执行：

```text
python -m scripts.manage check
python -m scripts.manage bootstrap
python -m scripts.manage admin-check
```

**没有migrate，没有DROP/TRUNCATE，没有清表步骤。** 数据库密码和管理员初始密码只在管理命令步骤注入环境变量；不作为命令行参数，不回显。管理员密码经Argon2id哈希后写入users；代码不打印手机号、密码或完整连接URL。

## 3. 怎样确认成功

运行记录为绿色，并在 **Check existing schema and initialize administrator** 步骤看到：

```text
Database schema v1 reachable.
Admin created.
Admin ready: enabled account with Argon2id password hash. No credentials displayed.
```

如果管理员已存在，第二行是：

```text
Admin already exists; unchanged.
```

这表示安全跳过；不会修改原管理员密码，也不会把已有普通用户提升成管理员。`admin-check`只检查存在启用的Argon2id管理员，不展示任何账户内容；最终还需要在部署后用你保存的手机号/密码实际登录确认。

你也可在Supabase SQL Editor运行以下**只读且不含敏感信息**的查询：

```sql
SELECT version FROM public.schema_migrations ORDER BY version;
SELECT count(*) AS administrator_count FROM public.users WHERE is_admin = true;
```

期望看到version **1**，首次初始化后管理员数 **1**。不要导出users表或把password_hash、完整手机号截图发到聊天。

## 4. 运行失败怎么办

红色不是成功，不要反复更改或重跑建表SQL。失败日志只显示异常类型：

- `check`失败：确认连接URL、数据库项目是否暂停、Session pooler主机/端口、密码编码、TLS根证书和Supabase网络限制；无需发送真实URL。
- 能连接但版本检查失败：用上面的只读查询检查version。正常完整SQL末尾已经写入1。如果没有1，不要盲目补版本号或重跑整份SQL；先核对SQL执行是否真正提交完整。
- `bootstrap`失败：确认手机号、12～128字符密码、已有同号普通账户的冲突。程序不会自动提权或删除同号账户。已有管理员时不创建第二位。
- `admin-check`失败：检查管理员是否被禁用或用户表有异常记录，不要手动写入明文密码。
- 看不到Actions/Run workflow：确保PR已合并main、GitHub Actions已启用且你拥有运行权限。仓库私有情况下需有可用GitHub Actions额度；平台可能要求计费或运行批准，先查看GitHub提示，不产生自己的服务器费用。

## 5. 清理一次性Secrets并部署Streamlit

确认成功后，回到GitHub **Settings → Secrets and variables → Actions**，删除刚添加的四个一次性Repository secrets（如其中某项本来供其他工作流使用，应先确认其他用途，不要直接删除共享配置）；不需要长期保留生产数据库访问能力。保留你的密码管理器记录。工作流不自动删除Secrets，也不会自动部署应用。

接着在 **Streamlit Community Cloud → Create app/New app → 选择仓库、main、app.py → Advanced settings → Secrets** 中填写正式运行配置，参考 `.streamlit/secrets.toml.example`：

- DATABASE_URL（同一数据库，保留TLS验证）。
- APP_SECRET_KEY（与上面一致）。
- DEEPSEEK_API_KEY、DEEPSEEK_MODEL以及预算/单价。
- **无需再填写ADMIN_INITIAL_PASSWORD**，管理员已保存在Supabase。ADMIN_PHONE也不参与正常登录校验，可不保留。

Secrets在GitHub与Streamlit之间**不会自动同步**。部署Python选择3.12，入口app.py。打开部署后的网页，用刚初始化的手机号和密码登录。登录后如需修改密码，在“我的 → 个人设置”修改；会话会全部失效，重新登录即可。登录成功并不自动证明金融源或AI已通过联调，仍需按DEPLOYMENT.md验收。

## 已有迁移版本的准确结论

`001_initial.sql` 包含事务，在结尾执行：

```sql
INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;
COMMIT;
```

因此，**整份SQL执行成功后无需单独补记version=1**。这次工作流只读检查版本，不修改schema_migrations、不调用metadata.create_all，也不会重建或清空任何现有表。

## 本次代码验证

开发环境完整回归测试 **35项通过**。新增测试在一次性PostgreSQL schema中执行同一份 `001_initial.sql`，随后只运行check/bootstrap/admin-check，验证初次成功、重复不变、删除初始凭据后仍能跳过，以及输出不含测试密码、手机号和连接URL。测试还验证版本检查在Python优化模式下依然生效。未连接你的正式Supabase，也未运行你账户中的GitHub Actions；正式初始化结果必须以你运行后的日志与实际登录为准。
