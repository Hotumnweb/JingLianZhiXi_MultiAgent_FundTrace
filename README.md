# “警链智析”——面向电诈资金图谱的自主协同智能体

> 项目仓库：<https://github.com/Hotumnweb/JingLianZhiXi_MultiAgent_FundTrace>
> 当前版本：**v0.3**（本地 Ollama 全链路跑通版；第二台 GPU 节点到货后切换即可）
> 参赛方向：新一代信息技术 / 网络安全 / 公安院校特色 + AI 智能体 + 大模型

## 1. 项目一句话

在**断网环境**下，用多智能体自动完成“银行流水解析 → Neo4j 资金图谱构建 → 三类图规则分析 → 本地大模型生成《资金穿透研判报告》”的完整链路，把“多名民警数天”的资金流研判压缩到“分钟级”。

## 2. v0.3 已完成能力

- ✅ 接入合成 AML 数据集：42,175 笔交易 / 3,500 个账户 / 22 个洗钱团伙；
- ✅ 多智能体编排：`supervisor → parsing_agent → graph_agent → report_agent`（LangGraph）；
- ✅ 三类图分析规则：多层归集（强证据）、环形转账（强证据）、快进快出（辅助证据）；
- ✅ **本地 Ollama 全链路跑通**：qwen2.5:7b-instruct（CPU，约 9 tok/s）生成完整四段式报告；
- ✅ 报告与证据自动落盘 `reports/`，前端可预览、可下载；
- ✅ 大模型不可用时自动降级为规则模板报告，链路不中断；
- ✅ 双模式推理层：本地 `127.0.0.1` ↔ 第二台 `192.168.50.2`，只改 `.env` 两行；
- ✅ 演示前自检脚本、Ollama 连通性检查、第二台一键配置脚本与部署手册。

## 3. 系统架构

```text
┌────────────────────────── 第一台电脑（Coordinator Node，无独显）──────────────────────────┐
│                                                                                          │
│  Streamlit 前端（app.py）                                                                 │
│        │                                                                                 │
│        ▼                                                                                 │
│  LangGraph Supervisor（确定性路由）                                                       │
│        │                                                                                 │
│        ├── parsing_agent：CSV 解析（pandas）→ 批量写入 Neo4j（Account / TRANSFER）        │
│        ├── graph_agent：三类图规则 + 环检测（Cypher + Python）                            │
│        └── report_agent：证据整理 → Ollama 生成研判报告 → 落盘 reports/                   │
│                                                                                          │
│  Neo4j 5.26（本机，heap 2G）        reports/（Markdown 报告 + 证据 JSON）                  │
└───────────────────────────────────────┬──────────────────────────────────────────────────┘
                                        │ HTTP 11434（断网局域网 / 本机回环）
                                        ▼
┌────────────────────────── 大模型推理层（可切换）────────────────────────────────────────┐
│ 当前阶段：第一台本机 Ollama（CPU，qwen2.5:7b-instruct）                                   │
│ 第二阶段：第二台 GPU 节点（RTX 5060 Laptop 8GB，qwen2.5:7b-instruct-q4_K_M）             │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## 4. 本地实测结果（第一台，纯 CPU）

| 环节 | 实测 |
| :--- | :--- |
| 解析 + 写入 Neo4j | 42,175 条交易 → 3,492 个账户 / 42,175 条边，约 15~30 秒 |
| 图规则分析 | 归集 10 个、环形链 12 条（覆盖 51 个账户）、快进快出 37 个 → 93 个可疑账户，约 5~10 秒 |
| 本地大模型报告 | qwen2.5:7b-instruct：输入 1,567 tokens，生成 1,055 tokens，**174 秒，9.03 tok/s** |
| 全链路总耗时 | 约 **167~205 秒**（多次运行波动，主要取决于 CPU 负载） |

报告样例见 [docs/sample_report.md](docs/sample_report.md)。

## 5. 目录结构

```text
JingLianZhiXi_MultiAgent_FundTrace/
├── .env                        # 本机配置（不提交，模板见 .env.example）
├── .env.example
├── README.md
├── requirements.txt
├── state.py                    # CaseState（含 evidence / report_path / llm_status）
├── main.py                     # 命令行入口（支持 --no-report / --check-llm）
├── app.py                      # Streamlit 前端
├── llms/
│   └── remote_llm.py           # Ollama 原生 API 接入层（本地/远程通用）
├── tools/
│   ├── parse_flow.py           # 流水解析（自动识别中文流水 / AML 数据集）
│   ├── graph_query.py          # Neo4j 写入 + 三条图规则 + 环检测
│   └── report_writer.py        # 报告/证据落盘 + 规则模板兜底报告
├── agents/
│   ├── parsing_agent.py
│   ├── graph_agent.py
│   └── report_agent.py
├── supervisor/
│   └── supervisor_node.py
├── scripts/
│   ├── generate_sample_data.py      # 生成 100 条演示数据
│   ├── evaluate_on_synthetic_aml.py # 图规则评测（精确率 / 召回率 / 团伙召回）
│   ├── check_llm.py                 # Ollama 连通性 + 最小推理测试
│   ├── preflight_check.py           # 演示前一键自检
│   └── second_node_setup.ps1        # 第二台 GPU 节点一键配置
├── docs/
│   ├── second_node_setup.md         # 第二台部署手册
│   └── sample_report.md             # 本地模型生成的报告样例
├── data/
│   ├── sample_flow.csv              # 100 条自造演示数据
│   └── synthetic_aml/               # 合成 AML 数据集（CC0）
└── reports/                         # 运行产物（git 忽略）
```

## 6. 数据说明与合规

| 文件 | 说明 |
| :--- | :--- |
| `data/synthetic_aml/transactions.csv` | 42,175 条交易，2025-01-01 ~ 2025-06-30，金额单位 USD |
| `data/synthetic_aml/accounts.csv` | 3,500 个账户，132 个洗钱账户（`is_synthetic_mule`） |
| `data/synthetic_aml/laundering_rings.csv` | 22 个团伙：12 个 Circular Loop + 10 个 Fan-Out Fan-In Smurfing |

- 数据集为**纯虚构合成数据**（CC0-1.0），不含真实公民信息，可安全用于比赛演示；
- **防标签泄漏**：`is_laundering / laundering_pattern / ring_id` 只在评测脚本中读取，
  智能体只能看到交易结构（时间、金额、收付款账号），避免“用答案破案”；
- 演示时可主动说明数据来源与合规处理，这是答辩加分项。

## 7. 图规则与检测效果

| 规则 | 判定条件 | 定位 |
| :--- | :--- | :--- |
| 多层归集（Fan-In） | 24 小时内 ≥4 个不同上游账户汇入，金额离散系数 CV ≤ 0.15 | 强证据 |
| 环形转账（Circular Loop） | 3~6 跳闭环，时间严格递增，每跳金额为上一跳的 90%~110%，跨度 ≤ 7 天 | 强证据 |
| 快进快出（Pass-through） | 48 小时内转出 ≥95% 收款金额，且账户总交易笔数 ≤ 8（卡农特征） | 辅助证据 |

评测结果（`python scripts/evaluate_on_synthetic_aml.py`）：

| 指标 | 结果 |
| :--- | :--- |
| 强证据合并（归集 + 环形） | 61 个账户，61 个命中，精确率 **1.000**，召回率 0.462 |
| 强证据 + 辅助证据 | 93 个账户，76 个命中，精确率 **0.817**，召回率 0.576 |
| 团伙级召回 | **22/22** 个洗钱团伙至少命中 1 个账户 |

## 8. 快速开始

### 8.1 前置

1. Neo4j 已启动（JDK 17，`localhost:7474` 可登录，密码与 `.env` 一致）；
2. Ollama 已启动，且 `ollama list` 有模型（本地或第二台节点）；
3. Python 环境：

```powershell
conda activate fraud_agent
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
```

### 8.2 常用命令

```powershell
# 检查本地/远程 Ollama 是否可用（连通性 + 最小推理 + tok/s）
python scripts/check_llm.py

# 演示前一键自检（依赖 / 数据 / Neo4j / Ollama / 报告开关）
python scripts/preflight_check.py

# 完整链路：解析 -> 图分析 -> 本地大模型报告（约 3 分钟）
python main.py

# 只跑图分析，不调用大模型（断网 / 无模型时）
python main.py --no-report

# 换数据源（100 条演示数据）
python main.py data/sample_flow.csv

# 图规则评测（先跑过 main.py 建图）
python scripts/evaluate_on_synthetic_aml.py

# 前端
streamlit run app.py
```

### 8.3 切换第二台 GPU 节点

第二台到位后，按 [docs/second_node_setup.md](docs/second_node_setup.md) 配置网络和 Ollama，
然后只改 `.env` 两行：

```env
OLLAMA_BASE_URL=http://192.168.50.2:11434
OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
```

先验证再切：

```powershell
$env:OLLAMA_BASE_URL = 'http://192.168.50.2:11434'
$env:OLLAMA_MODEL = 'qwen2.5:7b-instruct-q4_K_M'
python scripts/check_llm.py
```

## 9. 研判报告与证据

每次运行会在 `reports/` 生成一对文件：

- `YYYYMMDD_HHMMSS_report.md`：完整研判报告（Markdown，可下载）；
- `YYYYMMDD_HHMMSS_evidence.json`：结构化证据（可复核、可复现）。

报告包含四个部分：资金网络特征分析、高风险账户画像、侦查建议、方法与局限。
大模型不可用时自动降级为规则模板报告，并在报告头部标注。

## 10. 演示与“断网自证”

1. 第一台、第二台都断开 Wi-Fi / 外网；
2. `ping 8.8.8.8` 不通，`ping 192.168.50.2` 通；
3. 运行 `python scripts/preflight_check.py` 确认全部 OK；
4. 运行 `python main.py` 或 `streamlit run app.py`，展示：
   图分析证据 → 可疑账户 → 大模型研判报告 → 下载报告；
5. 讲解重点：强/弱证据分级、22/22 团伙召回、防标签泄漏、全离线推理。

## 11. 常见问题

| 现象 | 原因 / 解决 |
| :--- | :--- |
| `Ollama 不可达` | 启动 Ollama（`ollama serve` 或托盘程序），确认 `http://127.0.0.1:11434` 可访问 |
| `未找到模型` | 改 `.env` 的 `OLLAMA_MODEL` 为 `ollama list` 里的名字，或先 `ollama pull` |
| 本地生成报告很慢 | 正常：CPU 7B 约 2~4 分钟；赶时间用 `--no-report`，或等第二台 GPU |
| 报告被截断 | 调大 `.env` 的 `LLM_MAX_TOKENS`（默认 1400） |
| 报告状态 fallback | 大模型调用失败已自动降级，检查 Ollama 日志和 `check_llm.py` 输出 |
| Neo4j 连接失败 | 确认 `neo4j.bat console` 窗口未关、密码与 `.env` 一致 |
| Neo4j 启动报 Java 版本 | 启动前设置 `$env:JAVA_HOME` 到 JDK 17 |
| Streamlit 端口占用 | `streamlit run app.py --server.port 8502` |

## 12. 下一步（第三阶段）

- 团队分工落地：网络与算力（A/B）、AI 编排（C）、前端与主讲（D）；
- 前端增强：ECharts / PyVis 资金关系图、证据表格排序筛选、演示脚本一键化；
- 多智能体增强：话术判别智能体、元智能体动态路由（按资金穿透深度决定是否召唤新角色）；
- 第二台到货后：切换 GPU 节点、实测 tok/s 与断网演示、录制答辩视频。
