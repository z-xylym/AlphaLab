# 数据库连接失败：先运行只读诊断

`Operation failed: OperationalError` 只是SQLAlchemy/psycopg的连接错误外层类型，不能单凭它判断密码错误。不要继续盲目重置密码。这个诊断工具只输出固定类别与固定修复建议，不输出异常原文、SQLAlchemy URL、主机、IP、密码或手机号。

## 合并后如何运行（无需本地Python）

1. 合并诊断更新到 **main**。
2. 保留已有GitHub Repository Secrets；不用把任何值发给Codex，也不用重新配置管理员密码。
3. 仓库 **Actions → Initialize first administrator → Run workflow**。
4. Branch选择 **main**，confirmation输入 **DIAGNOSE**，点击 **Run workflow**。
5. 打开运行记录中的 **Diagnose database connection (read only)** 步骤，只查看 `DIAGNOSIS: 类别` 和下一行建议。

请发起新的Run workflow，不要点击旧失败记录的Re-run jobs；旧记录重跑可能仍使用旧提交，无法得到新增诊断。

**DIAGNOSE不会运行bootstrap或admin-check。** 只给诊断步骤注入DATABASE_URL，不注入管理员密码、手机号、APP_SECRET_KEY或DeepSeek Key。失败会使步骤变红，这是诊断发现问题的预期表现。成功应显示 `DIAGNOSIS: CONNECTED`，但只读诊断成功并不表示管理员已经初始化。

如需继续讨论，只提供 `DIAGNOSIS:` 后面的类别即可；不要发送完整日志、Secrets截图或异常原文。每次根据明确类别改正后再运行，避免没有变化的重复尝试。

## 类别和应对

| 类别 | 含义及操作 |
|---|---|
| CONFIGURATION_ERROR | URL格式/驱动前缀/必要字段有问题，或query参数覆盖了URL中的目标。核对Connect面板和密码URL编码，无需先重置密码。 |
| POOLER_CONFIGURATION_ERROR | 不是明确的5432 Session pooler配置，或pooler用户名缺少项目部分。使用你自己Connect页面提供的完整配置，不照抄他人项目。 |
| DNS_ERROR | runner无法解析目标主机或解析超时。核对主机拼写、项目Connect页面和DNS状态。 |
| NETWORK_ERROR | DNS已成功，但TCP失败，或后续连接出现网络超时、不可达、拒绝/重置。检查项目运行状态、5432端口及Supabase网络限制。超时不能单凭此类别断定是IP白名单还是防火墙。 |
| AUTHENTICATION_ERROR | 服务器报告认证失败，或Supavisor无法匹配租户/用户。核对Session pooler完整用户名、项目标识、密码URL编码和Secret粘贴完整性；也核对数据库访问限制。不要盲目重置密码。 |
| DATABASE_NOT_FOUND | 服务器明确报告数据库不存在。核对Connect面板的数据库名，通常为postgres；不新建或删除数据库来试错。 |
| TLS_CERTIFICATE_ERROR | 证书链验证失败、证书过期或主机名不匹配。保持verify-full，核对pooler主机和官方CA；不要修改为require/disable。 |
| TLS_CONFIGURATION_ERROR | TLS参数或根CA文件配置有问题，或者服务不支持所请求的TLS。保持verify-full；检查sslrootcert=system或官方CA路径。 |
| SCHEMA_VERSION_ERROR | 数据库已连接，但无法读取public.schema_migrations中的version=1，或没有该版本。只读核对表、权限和完整SQL执行结果，不重跑建表或盲目补版本号。 |
| OTHER_CONNECTION_ERROR | 当前规则不能安全细分的连接错误，可能需要查看Supabase控制台连接日志/服务状态。不会为增加信息而输出完整异常。 |
| CONNECTED | 配置、DNS/TCP、带原TLS配置的数据库连接和只读schema版本检查均成功；未改动用户或数据。 |

服务器连接阶段SQLSTATE可能不可用，因此诊断优先使用SQLSTATE，再在进程内部匹配libpq错误特征，最后返回固定类别。内部异常文本从不打印。上游错误含糊时会保留OTHER，而不假装已确认根因。

## 当前配置兼容性核查

- **驱动**：`postgresql+psycopg://` 对应SQLAlchemy 2 + psycopg 3；不是psycopg2前缀。
- **运行环境**：GitHub Actions为Ubuntu、Python 3.12，安装仓库固定依赖。当前验证的psycopg 3.2.12所带libpq是17.6，支持sslrootcert=system。代码本身未发现这三个设置之间必然不兼容的证据。
- **Session pooler**：使用Supabase Connect页的Session模式，明确端口5432；transaction模式通常使用6543，不应混用。共享pooler用户名通常形如postgres.PROJECT，以你实际Connect页为准。
- **TLS**：保留sslmode=verify-full。sslrootcert=system使用runner上的系统CA集合，支持这个参数**不代表系统集合一定信任实际服务器证书**。若得到TLS_CERTIFICATE_ERROR，应从Supabase官方项目面板取得正确公有根CA，上传公有证书至 `certs/supabase-root.crt`，把URL参数改为 `sslrootcert=certs/supabase-root.crt`。不得上传私钥，不从不可信地址下载CA，不关闭校验。证书主机名不匹配时应纠正主机，不能仅添加CA掩盖主机错误。
- **网络限制**：如果Supabase项目启用了Database Network Restrictions，检查其对当前连接端点的适用规则。GitHub标准托管runner出站IP可能变化；不要通过允许整个互联网来试错。如果诊断指向网络而限制确实生效，应使用可获准的固定出站IP runner、你已有的受信网络或与Supabase支持核对适用规则；这些可能涉及额外平台能力，代码不能替你保证放行。
- **只读**：诊断使用与应用相同的SQLAlchemy/psycopg连接路径、相同URL和10秒connect_timeout，并启用PostgreSQL只读事务。它不会修改TLS参数，不使用低级别无验证连接重试，也不改写用户URL去尝试其他主机。DNS/TCP只是连通预检，不发送数据库凭据；预检成功不保证TLS或认证成功。

## 版本核对与后续初始化

完整001_initial.sql末尾已经记录version=1。若诊断报告SCHEMA_VERSION_ERROR，只需先在Supabase SQL Editor运行：

```sql
SELECT version FROM public.schema_migrations ORDER BY version;
```

查询没有Secrets，也不改变数据。如果表存在但查询失败，核对连接角色和表权限；不要为修复应用连接而开放匿名角色访问。

诊断得到CONNECTED后，若确实尚无管理员，才再次Run workflow，把confirmation改为 **INITIALIZE**。同样先运行诊断，只有诊断成功才执行原来的check/bootstrap/admin-check；已有管理员会安全跳过，不重置密码或修改现有用户。

## 验证边界

测试使用合成错误与临时本地PostgreSQL；验证DNS、网络、认证、数据库不存在、TLS和未知错误分类，CLI输出不含测试Secrets，以及实际查询运行在只读事务且用户记录不变。没有连接你的正式Supabase，也没有运行你的GitHub runner；真正导致本次OperationalError的类别，需要由你合并后运行DIAGNOSE取得，不能仅凭之前的外层异常确定。
