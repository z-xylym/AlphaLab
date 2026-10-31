# AlphaLab V1.2 — Fast Research & AI Decision Assistant

分支：`feature/v1.2-fast-research`。基线：`1362d4a57e529b92f7b2f61a91b3ce82ee01e04c`。
本轮实现快速研究摘要与单股票追问；通过验证后提交分支并创建 PR 到 main，等待审核，不自动合并。

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

最新发布环境已确认 `DEEPSEEK_API_KEY` Secret 就绪且可由现有环境读取方式取得；`api.deepseek.com` 在已生效的允许域名中。未输出或保存真实凭据。

真实验证使用现有脚本的明确标记合成 Research Context（000000，非上市公司），仅连接一次性本地 PostgreSQL，不访问生产数据库。验证观察脚本、临时产物及真实 API 响应均保留在仓库外，未纳入版本控制。

| 路径 | HTTP | 耗时 | input | output | total | 重试 | 请求模型 → 实际模型 |
|---|---:|---:|---:|---:|---:|---|---|
| 默认 summary-only | 200 | 7.234s | 3000 | 591 | 3591 | 无 | deepseek-chat → deepseek-flash |
| V1.2 单股票追问 | 200 | 6.736s | 3669 | 805 | 4474 | 无 | deepseek-chat → deepseek-flash |

相对旧参考 11.023s、2925 input、1607 output、4532 total，本次摘要 total 减少941（20.76%），耗时减少3.789s。旧请求 Context 未保存，此比较为参考总量比较，不是相同 Context 的严格性能对照。

摘要通过现有 `parse_summary` schema 校验，只有 summary、不含 sections。两次真实输出均人工对照合成 Context 核验 grounding：没有从模型记忆补充公司事实，没有自行推导 PE/PB、市值或目标价，没有保证收益或直接买卖指令，明确说明缺失资料及合成性质。追问使用“如果我准备长期观察这家公司，最值得持续跟踪的三个指标是什么？”，请求 memory 为空，仅带当前 Context、精简摘要、用户研究偏好和有界历史，没有九章 sections。

最终完整测试：`239 passed, 1 warning`（48.26s），warning 为 XDG_RUNTIME_DIR 临时目录回退。summary-only 与旧 summary+sections 阅读、相同 fingerprint 九章复用、无 sections 追问兼容性均通过。浏览器首次运行遇到表格定位器临时匹配多个元素，重跑后1440 / 430 / 390全部通过，前后端外部请求均为0。真实验证无需修改应用代码。

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
