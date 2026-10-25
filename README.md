# “警链智析”——面向电诈资金图谱的元智能体调度系统

> 项目仓库：<https://github.com/Hotumnweb/JingLianZhiXi_MultiAgent_FundTrace>
> 当前版本：**v0.6 Coordinator 调度版**
> 定位：用元智能体做诈骗资金数据分析，第一台是调度中心，第二台提供 GPU 算力，第三台提供工具与图数据。

## 1. 三机架构

```text
┌───────────────────────────── Node1 调度中心（Coordinator）─────────────────────────────┐
│ 职责：只做任务下发、调度决策、状态管理、调用日志、结果汇总；不运行大模型、不运行图数据库。 │
│ 技术：LangGraph Supervisor · Streamlit 调度中枢 · 任务队列 · 证据/报告汇总                │
└───────────────┬───────────────────────────────────────────────────┬──────────────────────┘
                │ HTTP 11434（任务解析、多轮 AI 调用）                │ Bolt 7687 / 工具调用
                ▼                                                   ▼
┌───────────────────────────── Node2 GPU 算力中心 ─────────────────┐  ┌──────────── Node3 工具与图数据 ────────────┐
│ 状态：占位（待接入）                                              │  │ Neo4j 图数据库（账户 / 转账 / Cypher 规则）  │
│ 规划：Qwen3-4B 微调 + Qwen-Agent + Ollama，元智能体运行在此节点   │  │ pandas / pdfplumber 流水解析                 │
│ 职责：任务拆解、多轮决策、调用工具、总结结果                      │  │ 可选轻量嵌入模型（RAG）                      │
└───────────────────────────────────────────────────────────────────┘  └──────────────────────────────────────────────┘
```

**调度逻辑**：第一台下发任务 → 第二台元智能体解析任务并反复调用（任务拆解/多轮决策）→
调用第三台的数据与工具（Neo4j 查询、流水解析）→ 汇总结果回传第一台 → 第一台记录日志、
归档报告、展示证据。

**当前阶段**：第二台尚未到位，第一台用内置 LangGraph 调度器 + 本机 Ollama 完成开发联调；
第二台接入后只需修改 `.env`，平台会自动切换为“内网 GPU 节点”。

## 2. 第一台：元智能体调度中枢（平台）

平台是纯离线可用的深色调度中枢（Streamlit + Plotly），页面只保留实际岗位需要的内容：

| 页面 | 内容 |
| :--- | :--- |
| 调度总览 | 数据分析 KPI、任务队列状态、三节点集群状态、图规则命中、最近一次研判 |
| 元智能体调度 | 任务下发、提交队列/立即执行、阶段卡实时点亮、调度日志滚动、AI 报告逐 token 输出 |
| 任务队列 | 任务排队/执行状态、子智能体调用记录、中间结果汇总、任务详情与重跑 |
| 图数据与工具 | Node3 Neo4j 子图、环形链/归集明细、证据强度排行 |
| 规则与指标 | 三条图规则口径、当前命中、现场重算精确率/召回率/团伙召回 |
| 研判报告 | 报告预览、Markdown/证据 JSON 下载、证据明细 |
| 节点与工具 | 三节点状态、接口与工具清单、Node2 接入计划、调度日志、断网自检 |

第一台电脑的 Coordinator 职责落在平台上：
1. **任务队列**：提交任务入队、按顺序执行、失败/完成状态落盘 `runtime/tasks/`；
2. **Supervisor 调度**：LangGraph 编排器决定下一步调用解析、图查询还是 AI 报告；
3. **集群状态管理**：记录每次 Node1/Node2/Node3 调用耗时、中间结果与报告路径，支持任务重跑；
4. **追加指令**：任务完成后可继续下发补充侦查指令，结果回写到同一任务。

启动：

```powershell
conda activate fraud_agent
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
streamlit run app.py
```

本地实测：平台六页 AppTest 全部无异常；完整流式链路可产生 892 个 token 事件；
本地 CPU 调试模式下，报告生成约 2~4 分钟（第二台 GPU 接入后会明显缩短）。

## 3. 当前状态与演示数据

- 第二台 GPU 节点：**占位**，目标地址 `192.168.50.2`，规划模型 Qwen3-4B 微调 + Qwen-Agent；
- 第三台工具与图数据节点：开发调试阶段部署在本机（Neo4j + pandas），目标地址 `192.168.50.3`；
- 为保证比赛现场由队员亲自操作演示，**报告、证据、调度日志和 Neo4j 图谱缓存已清空**；
- 现场打开平台后，从“元智能体调度”下发任务即可重新建图、生成报告；
- 需要清理时执行：`python scripts/reset_demo_data.py --graph`。

## 4. 目录结构

```text
JingLianZhiXi_MultiAgent_FundTrace/
├── app.py                       # 调度中枢入口（六页面导航）
├── workbench/
│   ├── theme.py                 # 深色大屏样式与组件
│   ├── services.py              # 节点状态、报告索引、调度日志、指标计算
│   ├── tasks.py                 # 任务队列/任务记录（runtime/tasks）
│   ├── coordinator.py           # Supervisor 调度执行、调用记录、中间结果、追加指令
│   ├── runner.py                # 流式编排器（阶段 + token 事件）
│   ├── graph_view.py            # Plotly + NetworkX 资金网络图
│   └── pages/                   # 七个页面（含任务队列）
├── main.py                      # 命令行入口（--no-report / --check-llm）
├── llms/remote_llm.py           # Ollama 原生 API（生成 / 流式生成 / 健康检查）
├── tools/
│   ├── parse_flow.py            # 自动识别中文流水 / AML 数据集
│   ├── graph_query.py           # 建图、三条规则、环检测、子图查询
│   └── report_writer.py         # 报告/证据落盘 + 兜底报告
├── agents/                      # parsing / graph / report 智能体
├── supervisor/supervisor_node.py
├── scripts/
│   ├── reset_demo_data.py       # 清理报告/证据/缓存，可选清空 Neo4j
│   ├── evaluate_on_synthetic_aml.py
│   ├── check_llm.py
│   ├── preflight_check.py
│   ├── generate_sample_data.py
│   └── second_node_setup.ps1
├── docs/
│   ├── platform_guide.md        # 平台功能与现场演示脚本
│   └── second_node_setup.md     # 第二台 GPU 节点部署手册
├── data/
│   ├── sample_flow.csv          # 100 条演示数据
│   └── synthetic_aml/           # 合成 AML 数据集（CC0）
├── reports/                     # 运行产物（报告 + 证据 + 调度日志，git 忽略）
└── runtime/tasks/               # 任务队列与任务记录（git 忽略）
```

## 5. 数据说明与合规

- `data/synthetic_aml/transactions.csv`：42,175 条交易，金额单位 USD；
- 3,500 个账户，132 个洗钱账户；22 个团伙（12 环形 + 10 集散式）；
- 纯虚构合成数据（CC0-1.0），不含真实公民信息；
- **防标签泄漏**：`is_laundering / laundering_pattern / ring_id` 只在评测脚本读取，
  智能体只看到交易结构，避免“用答案破案”。

## 6. 图规则与实测指标

| 规则 | 判定条件 | 定位 |
| :--- | :--- | :--- |
| 多层归集 | 24 小时内 ≥4 个上游账户汇入，金额离散系数 CV ≤ 0.15 | 强证据 |
| 环形转账 | 3~6 跳闭环，时间递增，每跳金额为上一跳的 90%~110%，跨度 ≤7 天 | 强证据 |
| 快进快出 | 48 小时内转出 ≥95% 收款金额，且账户交易笔数 ≤8 | 辅助证据 |

离线评测（`python scripts/evaluate_on_synthetic_aml.py`）：

| 指标 | 结果 |
| :--- | :--- |
| 强证据合并（归集 + 环形） | 61 个账户，61 个命中，精确率 **1.000**，召回率 0.462 |
| 强证据 + 辅助证据 | 93 个账户，76 个命中，精确率 **0.817**，召回率 0.576 |
| 团伙级召回 | **22/22** 个洗钱团伙至少命中 1 个账户 |

## 7. 常用命令

```powershell
streamlit run app.py                          # 启动调度中枢
python main.py                                # 命令行完整链路（含 AI 报告）
python main.py --no-report                    # 只跑图工具分析
python scripts/check_llm.py                   # 检查调试推理服务
python scripts/preflight_check.py             # 演示前自检
python scripts/evaluate_on_synthetic_aml.py   # 规则评测
python scripts/reset_demo_data.py --graph     # 清理演示缓存与图谱
```

## 8. Node2 接入

按 [docs/second_node_setup.md](docs/second_node_setup.md) 部署第二台后修改 `.env`：

```env
OLLAMA_BASE_URL=http://192.168.50.2:11434
OLLAMA_MODEL=你的Qwen3-4B微调模型名
```

先验证再切：

```powershell
$env:OLLAMA_BASE_URL = 'http://192.168.50.2:11434'
$env:OLLAMA_MODEL = '你的Qwen3-4B微调模型名'
python scripts/check_llm.py
```

平台“节点与工具”页的 Node2 状态会从“占位”切换为“在线”，任务拆解与多轮 AI 调用交给
Node2 上的 Qwen-Agent 元智能体。

## 9. 现场演示（建议 5~8 分钟）

1. **调度总览**：三节点分工、Node2 占位说明、任务队列状态；
2. **元智能体调度**：提交任务到队列或立即执行，展示阶段卡、日志与报告逐 token 生成；
3. **任务队列**：执行排队任务、查看调用记录与中间结果、任务重跑；
4. **图数据与工具**：展示 Node3 的图规则结果与资金网络；
5. **规则与指标**：现场重算精确率/召回率与团伙级召回；
6. **研判报告**：打开报告、下载报告与证据；
7. **节点与工具**：展示节点状态、Node2 接入计划、调度日志与断网自检；任务完成后可追加侦查指令。

完整讲解词见 [docs/platform_guide.md](docs/platform_guide.md)。

## 10. 常见问题

| 现象 | 原因 / 解决 |
| :--- | :--- |
| 平台页面为空 | 演示数据已清理；在“元智能体调度”下发任务即可重建 |
| Node2 显示“占位” | 第二台尚未接入；开发调试使用本机 Ollama 临时推理 |
| Node3 显示离线 | Neo4j 未启动；用 JDK 17 启动后刷新节点状态 |
| AI 报告很慢 | 本地 CPU 调试约 2~4 分钟；可点“仅执行图工具分析”快速演示 |
| 报告状态 fallback | AI 不可达，自动降级为规则模板报告 |
| 需要重置演示环境 | `python scripts/reset_demo_data.py --graph` |
