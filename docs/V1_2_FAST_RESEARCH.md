# AlphaLab V1.2 — Fast Research & AI Decision Assistant

分支：`feature/v1.2-fast-research`。基线：`1362d4a57e529b92f7b2f61a91b3ce82ee01e04c`。
本轮仅恢复指定功能；未 commit、push 或创建 PR。

## 功能与契约

- 个股概览不读取日线。走势只读已有缓存，无缓存时显示“获取走势”，点击后只调用原 Sina 日线；成功当轮出图，失败可单独重试。财务和主营同样有独立获取入口，保留原有显式批量刷新。
- 未打开的普通个股页签不执行对应正文读取。AI 页构建 Context 时只读已有缓存，绝不自动获取日线或其他外部数据。
- 首页 `read_home_sections` 移除未使用 spot；偏好与自选在同一轮渲染中复用。报告状态使用 EXISTS 风格限一行查询；自选报告日期使用轻量投影，不读100份完整正文。研究库选择记录复用已经取得的用户记录。
- 行业目录以无正文版本查询配合1800秒会话缓存；推荐按当前会话身份、偏好、目录版本及候选公司相关资料版本复用。失效包括刷新、删除及过期状态变化。身份校验仍在服务端实时执行。
- 财务展示只对源明确标注“元”的指标转换为万元/亿元；未知单位不猜测。关键负净利润、ROE、经营现金流使用克制的风险色；底层原值、报告期和来源不变。
- 默认“生成AI研究”调用 `company_summary`，仅接受 `{summary: ...}`，拒绝 sections。观点限定四种；事实最多5条，风险与改变条件各最多3条；保留原 grounding 禁止事项。
- 九章仍使用原 `company_report`、`company-report-v1.1` 键契约；只有点击“生成完整研究依据”才生成。摘要采用独立 `company-summary-v1.2` 键契约，均纳入 Context fingerprint 与模型。相同 fingerprint 的完整报告可复用；摘要更新不覆盖全文。旧 Context 的全文保留并提示较早数据。
- 旧 sections-only、旧 summary+sections 与新 summary-only 均可阅读。历史组合报告可按原 fingerprint 复用。无 sections 不阻塞追问。
- “继续问 AlphaLab”仅发送问题时调用既有 AI budget / permission / DeepSeekClient。资料为当前 Context、最新精简摘要、当前用户偏好及有限历史。已有 summary 时不发送九章。使用既有 `chat_messages` 的 `stock:<code>` 私有记录，按用户与股票隔离；最多4轮，JSON历史最多5000字符/14000 UTF-8字节。失败不改旧报告与历史，不向研究库写入追问副本。

数据库 schema、迁移、认证、生产数据 provider、TLS、Secrets 读取与生产配置文件均未修改。所有测试、浏览器与性能验证仅使用一次性本地 PostgreSQL 和明确隔离夹具。

## 验证

定向测试通过；最终完整测试 `239 passed, 1 warning`（47.30s）。warning 为 pgserver/platformdirs 的 XDG_RUNTIME_DIR 回退提示。

命令：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.browser_check
.venv/bin/python -m scripts.benchmark_research
```

服务端页面函数渲染耗时；不包含 AppTest 调度及浏览器往返，cold 为本次会话首次渲染，rerun 为后续3次中位数。数据量与旧参考未严格配对，不能据此宣称精确百分比性能提升。

| 页面 | cold ms | rerun ms | cold/rerun 查询数 |
|---|---:|---:|---:|
| 首页 | 64.67 | 22.95 | 18/6 |
| 个股概览 | 13.85 | 9.59 | 4/2 |
| 财务 | 10.85 | 11.3 | 2/2 |

1440 / 430 / 390 最终浏览器检查全部通过：导航、触控高度、无横向溢出、summary-only 与九章分别阅读、无缓存走势入口均通过；三尺寸前端外部请求与后端外部调用尝试均为0。普通页面性能浏览的外部调用尝试也为0。最终浏览器结果见 `test-results/terminal-results.json`（仅当前实例本地产物，已忽略）。

## 真实 DeepSeek 验证

待本地与浏览器门禁完成后，运行 `.venv/bin/python -m scripts.validate_v12_ai`。脚本只使用显式合成 `000000` Context 和一次性本地数据库；不会连接环境中的生产 DATABASE_URL，不使用600519冒充真实资料；按摘要→追问顺序执行。保留真实 HTTP 状态、模型、耗时、tokens 及相对4532的参考总量差，失败不输出密钥、数据库连接或供应商正文。

本地门禁全部通过后已执行该脚本，退出码2：`DEEPSEEK_API_KEY not configured`，真实API调用数0。当前运行实例无 DeepSeek 密钥绑定，网络允许列表也未包含 api.deepseek.com。已在开发环境配置草稿中保存 DEEPSEEK_API_KEY 要求及 api.deepseek.com 目的域名；草稿保存尚未应用到运行实例，也未发布。请在环境设置中安全配置并保存，使绑定及网络策略生效后继续本脚本。

本轮 summary-only 的真实耗时、input/output/total tokens、相对4532的下降量均**未取得，不能计算**；真实单股票追问同样**未执行**。模拟服务的追问隔离、预算、历史上限及失败保留测试已通过，不能等同于真实DeepSeek验收。旧4532 total 与旧追问4983 total 只是用户提供的参考，不能替代本轮验证。机器可读阻塞记录为 `test-results/v12-live-ai.json`。

## 文件清单

- `alphalab/ai.py`
- `alphalab/company_report.py`
- `alphalab/data.py`
- `alphalab/personalization.py`
- `alphalab/repository.py`
- `alphalab/stock_chat.py`
- `alphalab/ui/__init__.py`
- `alphalab/ui/company_ai.py`
- `alphalab/ui/components.py`
- `alphalab/ui/home.py`
- `alphalab/ui/preferences.py`
- `alphalab/ui/reads.py`
- `alphalab/ui/recommendations.py`
- `alphalab/ui/report_view.py`
- `alphalab/ui/stock.py`
- `alphalab/ui/workspace.py`
- `assets/styles.css`
- `docs/V1_2_FAST_RESEARCH.md`
- `scripts/benchmark_research.py`
- `scripts/browser_check.py`
- `scripts/validate_v12_ai.py`
- `tests/test_market_diagnostics.py`
- `tests/test_streamlit.py`
- `tests/test_terminal_ui.py`
- `tests/test_v12_research.py`
