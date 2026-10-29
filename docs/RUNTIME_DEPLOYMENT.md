# 正式部署：应用运行时显式Supabase CA

管理员已经初始化成功。本次只更新Python配置、运行时engine与CA生命周期，不执行迁移、不创建/修改用户、不改变业务功能。

## Streamlit Community Cloud Secrets

GitHub Actions Secrets不会自动同步到Streamlit。请在 **Community Cloud → Create app/New app → Advanced settings → Secrets**，或已部署应用 **Settings → Secrets** 填入服务端配置。

必需：

| 名称 | 内容 |
|---|---|
| DATABASE_URL | 你已经验证成功的同一Session pooler、5432、postgresql+psycopg连接URL，保持sslmode=verify-full；无需重新修改密码或重编码URL。 |
| APP_SECRET_KEY | 原来使用的强随机应用密钥，至少32字符；不要填模板占位符。 |
| SUPABASE_CA_CERT | 如果仓库没有certs/supabase-ca.crt，填写原来验证成功的官方完整CA PEM，格式如下。 |

启用AI时还需DEEPSEEK_API_KEY、DEEPSEEK_MODEL，以及核对每日预算、次数和Token单价。没有AI Key时应用明确显示AI待配置，不影响已有账户的数据库登录。**运行时不需要ADMIN_PHONE或ADMIN_INITIAL_PASSWORD**，不在应用启动时再次初始化管理员。

CA Secret的TOML格式示意（将省略内容换成你自己的官方完整CA，不能照抄省略号）：

```toml
SUPABASE_CA_CERT = """
-----BEGIN CERTIFICATE-----
此处填写从Supabase官方项目面板下载、且已经验证成功的完整PEM内容
-----END CERTIFICATE-----
"""
```

真实数据库密码、连接URL、API Key只填平台Secrets，不发到聊天，不提交GitHub。证书本身是公有CA，也可以按既有方式放入仓库 **certs/supabase-ca.crt**；仓库CA优先，Secret次之。无效仓库CA会失败，不尝试用Secret或系统信任库掩盖问题。

原URL中即使写有sslrootcert=system，运行时也只在内存中替换为已验证CA私有快照的绝对路径。原Secret不会被修改，host/user/password/dbname/5432/verify-full不变；不记录或输出替换后的URL。

## 为什么不会在页面重跑后丢失CA

- 远程生产连接通过现有explicit_ca_url()验证与生成CA，未实现另一套TLS校验。
- engine由线程安全、进程级资源注册表持有，同一配置在不同用户和页面重跑之间复用。
- Secret CA在0600临时文件中；仓库CA同样复制成私有快照，防止仓库文件更新/替换破坏旧池的后续重连。
- CA上下文一直保留到**进程退出**。单次页面返回、Session State重置、engine.dispose()后池重建都不会删除CA。
- 不用LRU淘汰：配置变化后旧engine可能还被会话引用，旧CA也保留到进程退出。资源释放函数只供进程关闭时使用，不能在页面重跑或手动清缓存时调用。
- 正常退出先dispose空闲连接池，再关闭CA上下文；进程结束后平台还会清理临时文件系统。不依赖运行目录长期保存任何用户数据。

修改CA、URL或其他运行Secrets后，请 **Reboot app**，而不是只刷新浏览器。仓库CA更新也必须重新部署/重启进程；这保证使用一个明确的证书快照，不在活跃会话之间热替换信任根。

若短进程bootstrap已给子进程准备了显式CA文件URL，新运行时仍兼容：没有仓库CA和Secret时，通过同一个helper验证并快照该显式文件。这里不会把system当作文件路径使用，也不会回退系统信任库。原bootstrap/diagnostic命令继续保留。

本地临时PostgreSQL（localhost/Unix socket）仅保留既有开发测试路径；这不是生产Supabase连接失败时的降级路径。

## 部署步骤

1. 合并本次运行时CA PR到main，确认生产数据库和已初始化管理员保持原样。
2. 打开 [Streamlit Community Cloud](https://share.streamlit.io/)，连接你有权限的GitHub账号和私有仓库。
3. 创建应用，仓库 **z-xylym/AlphaLab**，分支 **main**，入口 **app.py**，Python **3.12**。
4. 在平台Secrets里配置以上内容；使用现有成功的官方CA和连接信息，不将Actions的临时文件路径复制过来。
5. Deploy；已有部署则更新main、保存Secrets并Reboot app。安装依赖只用requirements.txt，不在启动命令中加migrate/bootstrap。
6. 打开平台提供的真实应用网址，先检查登录页，再用已有管理员手机号/密码登录。

若出现“数据库安全连接配置未完成”，检查CA是否完整、名称是否拼对、是否保存到Streamlit而非仅GitHub、是否已Reboot、verify-full与Session pooler是否保持不变。不要先重置密码，也不要关闭证书验证。数据库连接异常同样不展示底层异常或URL。

## 第一轮生产验收

- 登录页没有安全连接配置告警；已有管理员可登录，后台显示原有账号，退出后可重新登录。
- 浏览器刷新/页面切换后可重新登录并继续读取原有记录，未产生第二个管理员；必要时通过受信平台确认schema版本仍为1（无需再迁移）。
- 用应用允许的现有功能保存一条自己的偏好或自选；退出、Reboot app再登录，验证记录仍在。不要修改其他用户或删除生产表。
- 用两个独立用户验证私人历史和持仓隔离；普通用户不显示管理入口。
- 观察应用运行一段时间后登录与读取仍可用。开发测试已覆盖池dispose/重建时CA仍存在；不要在生产开放调试端点或主动中断其他人的连接来测试。
- 若配置AI，主动生成一次研究，确认报告保存和额度记录；重复相同请求不重复计费。缺Key或源不可用时应明确提示，不生成假行情。
- 检查市场/财务来源与日期、官方政策原文链接和375/390/430px阅读；外部数据云IP限制与数据库TLS是不同问题，分别记录。
- 确认应用界面及可查看的运行日志没有URL、密码、CA内容或Key。不要为了排查启用SQL echo/打印Settings或环境变量。

这些是你部署后执行的验收清单，代码测试不等于已完成正式公网验收。

本次开发环境完整回归：**121项测试通过**，包含原bootstrap/diagnostic、真实libpq TLS握手、运行时快照优先级与安全失败、Streamlit配置读取、真实本地连接池dispose后重连，以及页面错误脱敏。测试未连接正式Supabase，也未代替你执行Community Cloud公网部署。
