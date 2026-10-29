# Supabase Session pooler：显式CA，只验证连接

本次已确认TLS_CERTIFICATE_ERROR，后续不再重置或检查数据库密码，不降低TLS级别。新工作流 **Verify Supabase CA connection (read only)** 只做DIAGNOSE，没有管理员初始化命令，也不接收管理员/AI Secrets。原管理员工作流暂不使用。

## 1. 下载正确的官方CA

在你自己的 **Supabase Dashboard → Database Settings → SSL Configuration** 下载该项目的 **Server root certificate / CA certificate**（PEM格式）。界面名称可能随平台更新，使用官方项目面板下载入口。

官方参考：[SSL Enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement)。不要从聊天、第三方网站或不受信的失败连接中复制证书作为信任根。不要将服务器私钥上传仓库。

## 2. 推荐：作为公有CA文件放入仓库

本PR合并到main后，打开仓库的 **certs** 目录 → **Add file → Upload files**，上传刚下载的原始CA，将文件名设为：

`certs/supabase-ca.crt`

只上传公有CA文件；不要上传包含数据库URL/密码的配置文件、.env、secrets.toml或任何私钥。如果GitHub要求通过PR提交该文件，合并该CA文件PR后再运行验证。证书可以公开保存但仍是安全敏感的信任配置：只接受项目官方来源，审核后再合并。

这次代码没有你的官方项目CA，仓库中只有说明文件，**没有伪造的.crt占位文件**。没有提供有效CA时，诊断会安全停止。

### 可选：不提交证书文件，使用GitHub Secret

仓库 **Settings → Secrets and variables → Actions → New repository secret**：

- Name：`SUPABASE_CA_CERT`
- Secret：官方CA的完整PEM内容，包括BEGIN CERTIFICATE/END CERTIFICATE及真实换行。

这是CA本身，不是密码。不要在这里填私钥、数据库密码或完整URL。代码会将它写到GitHub runner临时目录中的独立0600文件，诊断结束（包括失败）后删除；不会将内容输出日志、存为构建产物或写进GITHUB_ENV。

若仓库文件和Secret同时存在，**仓库文件优先**。仓库CA损坏时直接失败，不会偷偷换用Secret或system来掩盖配置错误。

## 3. 不需要修改DATABASE_URL Secret或密码

继续使用现有Secrets里的Session pooler连接，保持：

- `postgresql+psycopg://`；SQLAlchemy + psycopg 3。
- 原来的Session pooler hostname及用户名，不换直连或transaction pooler。
- 5432端口（显式5432或PostgreSQL默认端口）。
- `sslmode=verify-full`，不会把require/disable自动升级后偷偷继续。

新脚本只在内存中把URL的 **sslrootcert** 替换为已验证CA文件的绝对路径。不会输出或存储这个URL，不更改密码、主机、用户名、数据库或其他参数。原Secret即使写着sslrootcert=system，**新工作流实际连接时也只使用显式CA文件**，不加载系统信任存储。

脚本只接受Supabase共享Session pooler域名与5432，拒绝hostaddr/host/service等query覆盖，以避免TLS身份验证与实际目标分离。它验证PEM可读、只含证书且至少有一个CA，拒绝私钥/空文件/损坏文件；CA来源的真实性仍由官方下载与代码审核保证。叶子/CA的实际有效期、签名和链由TLS握手验证。

## 4. 重新执行DIAGNOSE

1. 确保本PR和官方CA文件（或Secret）已经准备好。
2. 仓库 **Actions → Verify Supabase CA connection (read only)**。
3. 点击 **Run workflow**，Branch选择 **main**，再次点击 **Run workflow**；不需要填写INITIALIZE。
4. 打开 **DIAGNOSE with official CA and hostname verification** 步骤。

请启动新的运行，不重跑旧失败任务，旧任务可能仍使用旧代码。此工作流只注入DATABASE_URL和可选CA Secret，不注入APP_SECRET_KEY、管理员密码、手机号或DeepSeek Key。

成功应显示：

```text
DIAGNOSIS: CONNECTED
```

它表示TLS连接与只读schema版本检查成功，**不表示管理员已经初始化**。本证书验证工作流到这里停止，不创建管理员。连接验证成功后，如需初始化，请按 [显式CA管理员初始化](ADMIN_BOOTSTRAP_CA.md) 使用已经修复的管理员链路，不能重跑旧提交的初始化任务。

## 5. 错误类别怎样判断

| 类别 | 下一步 |
|---|---|
| TLS_CA_CONFIGURATION_ERROR | 检查CA是否上传到精确路径，或CA Secret是否为完整PEM；不能上传私钥、叶子证书或示例文件。 |
| TLS_HOSTNAME_MISMATCH | TLS服务端叶子证书的SAN/CN不能匹配原pooler hostname。核对Supabase Connect页该项目Session pooler的主机，向Supabase确认适用端点；不要换成证书中任意域名、改hostaddr或关闭主机名验证。 |
| TLS_CERTIFICATE_ERROR | 仍有链、签名或有效期问题。确认官方CA确实适用于当前共享pooler的实际证书链；仅下载某个项目CA不能证明它一定签发当前pooler证书。核对官方CA更新/轮换，并向Supabase确认该pooler使用的官方信任链。不要从未知来源拼接CA，也不回退system。 |
| CONNECTED | 连接及schema检查通过；先停止，不执行管理员初始化。 |

证书**根CA自己的CN**并不是数据库服务器主机名；不应该拿根CA的CN直接与pooler hostname比较。主机名核对由libpq的verify-full在真实握手中针对服务器叶子SAN/CN执行，使用原URL的hostname。无需运行会打印整张证书的openssl s_client命令。

对于共享pooler，如果官方项目CA与pooler证书链不同，这次显式CA验证仍可能失败；不能在没有真实握手结果时声称已经修复。只把固定DIAGNOSIS类别告诉开发者即可，不发送完整异常、证书内容、URL或Secrets截图。

## 6. Ubuntu/Python/驱动和测试边界

新工作流使用Ubuntu、Python 3.12及仓库固定SQLAlchemy/psycopg 3依赖，CA路径在Python内解析为绝对路径；Secret路径权限为0600，runner同一用户的psycopg可读取。证书和URL不通过shell拼接或回显。

新增测试用临时自签测试CA和最小PostgreSQL协议TLS测试服务，用真实psycopg/libpq握手验证：正确CA+匹配SAN成功；错误CA失败；正确CA+不匹配SAN失败。TLS测试服务不是正式数据库；原有临时PostgreSQL继续验证只读schema查询。测试私钥只在临时目录生成，从不写入仓库。另测试来源优先级、缺失/损坏/私钥/叶子文件拒绝、临时文件清理、URL其他字段不变、日志不泄漏及只读工作流没有初始化命令。

真实Supabase项目证书、pooler证书链和该项目hostname尚未提供给开发环境，因此生产信任链与SAN匹配必须由你在新工作流中验证；不会假称已经验证成功。

本次开发环境完整回归：**97项测试通过**（2026-10-29）。这些结果不替代你的GitHub runner对正式Supabase端点的验证。
