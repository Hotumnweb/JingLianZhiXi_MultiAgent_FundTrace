# 警链智析-元智能体驱动的涉诈资金穿透研判系统

> 项目仓库：<https://github.com/Hotumnweb/JingLianZhiXi_MultiAgent_FundTrace>
> 当前版本：**v1.1 三机联调 + 元智能体 + 数据资产 + 真实数据接入清洗**
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
│ 状态：已接入（随身 WiFi 热点联调）                                │  │ Neo4j 图数据库（账户 / 转账 / Cypher 规则）  │
│ 模型：qwen3.5-9b-tools:q4km（Q4_K_M，think=false）                │  │ pandas / pdfplumber 流水解析                 │
│ 职责：任务拆解、多轮决策、调用工具、总结结果（Qwen-Agent 待启动）  │  │ 可选轻量嵌入模型（RAG）                      │
└───────────────────────────────────────────────────────────────────┘  └──────────────────────────────────────────────┘
```

**调度逻辑**：第一台下发任务 → 第二台元智能体解析任务并反复调用（任务拆解/多轮决策）→
调用第三台的数据与工具（Neo4j 查询、流水解析）→ 汇总结果回传第一台 → 第一台记录日志、
归档报告、展示证据。

**当前阶段**：第二台已通过随身 WiFi 热点接入（`192.168.0.200`），第一台通过
`http://192.168.0.200:11434` 调用其 Ollama 模型生成研判报告；第三台工具节点暂由本机
Neo4j 承担。比赛现场可换成固定内网，只改 `.env`。

## 2. 第一台：元智能体调度中枢（平台）

平台是纯离线可用的深色调度中枢（Streamlit + Plotly），页面只保留实际岗位需要的内容：

| 页面 | 内容 |
| :--- | :--- |
| 调度总览 | 数据分析 KPI、任务队列状态、三节点集群状态、图规则命中、最近一次研判 |
| 元智能体调度 | 固定 Supervisor 流水线：任务下发、提交队列/立即执行、阶段卡实时点亮、调度日志滚动、AI 报告逐 token 输出 |
| 元智能体自主分析 | Qwen3.5 工具调用实验台：模型自主选择归集/快进快出/资金往来/规则指标工具，Node1/Node3 执行并回传，展示决策轨迹 |
| 任务队列 | 任务排队/执行状态、子智能体调用记录、中间结果汇总、任务详情与重跑 |
| 数据资产 | data/new 数据集目录、确定性抽样生成、样本预览与规则评测 |
| 数据接入 | 真实混乱数据接入：自动识编码/分隔符/列名、字段映射、复合账号、流式清洗、pandas 分析台 |
| 图数据与工具 | Node3 Neo4j 子图、环形链/归集明细、证据强度排行、Neo4j 复核查询 |
| Neo4j 操作台 | 现场执行只读 Cypher：图谱规模、Top 入度、快进快出、账户资金往来、约束与索引 |
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

本地实测：平台十一页 AppTest 全部无异常；完整流式链路可产生 892 个 token 事件。
**跨机实测（2026-10-26）**：第一台解析 42,175 条流水 + 建图 + 图分析，第二台 RTX 5060
生成研判报告耗时 **28.65 秒（34.53 tok/s）**，全链路 **71.9 秒**。
**元智能体工具调用实测**：Qwen3.5 自主调用归集查询 + 快进快出查询，2 轮完成，约 16 秒。

## 3. 当前状态与数据资产

- 第二台 GPU 节点：**已接入**，IP `192.168.0.200`，模型 `qwen3.5-9b-tools:q4km`，
  必须 `LLM_THINK=false`；详细说明见 [docs/NETWORK_NODE2.md](docs/NETWORK_NODE2.md)；
- 第三台工具与图数据节点：开发调试阶段部署在本机（Neo4j + pandas）；Neo4j 连接地址
  统一用 **IP + 端口** 配置（`.env` 的 `NEO4J_HOST` / `NEO4J_PORT`，本机回环即
  `127.0.0.1` + `7687`），部署到 Node3 时只改这两行（当前规划 `192.168.0.201` + `7687`）；
  连接自检：`python scripts/check_neo4j.py`；
- Neo4j 已监听 `0.0.0.0`，并在第一台放行 TCP **7474 / 7687**：第二台可直接用浏览器访问
  <http://192.168.0.199:7474>（Bolt `bolt://192.168.0.199:7687`）；换机器时按
  [docs/runbook_manual_operation.md](docs/runbook_manual_operation.md) 的 2.1.1 节配置；
- 本次联调已生成一份报告与图谱；比赛前可运行 `python scripts/reset_demo_data.py --all`
  恢复干净环境（图谱、报告、任务、上传流水全部清空），由队员现场重新建图、生成报告；
- **数据接入**：真实一手数据不必上传——直接选 `data/new` 原始文件（几百 MB），自动识别
  编码（含 GBK/GB18030）、分隔符（逗号/分号/Tab/竖线）、表头与列名，支持“银行+账号”复合账号、
  多格式时间与 ￥/千分位金额；流式清洗后输出统一流水并建图。也内置 `data/samples/bank_flow_format_sample.csv`
  格式样例（GBK、分号、￥、混合日期、空账号、自转账、重复行）用于格式适配验证；
  详见 [docs/DATA_CLEANING_GUIDE.md](docs/DATA_CLEANING_GUIDE.md)；
- **数据资产**：`data/new/` 已落地 5 套公开大数据集（IBM AML HI/LI、PaySim、Elliptic、
  IEEE-CIS，约 2.5 GB，git 忽略），由 `scripts/prepare_datasets.py` 生成确定性抽样到
  `data/prepared/` 后现场使用；平台“数据资产”页统一管理与评测，详见
  [docs/DATASET_GUIDE.md](docs/DATASET_GUIDE.md)；

## 4. 目录结构

```text
JingLianZhiXi_MultiAgent_FundTrace/
├── app.py                       # 调度中枢入口（十页面导航）
├── workbench/
│   ├── theme.py                 # 深色大屏样式与组件
│   ├── services.py              # 节点状态、数据资产、报告索引、调度日志、指标计算
│   ├── tasks.py                 # 任务队列/任务记录（runtime/tasks）
│   ├── coordinator.py           # Supervisor 调度执行、调用记录、中间结果、追加指令
│   ├── runner.py                # 流式编排器（阶段 + token 事件）
│   ├── graph_view.py            # Plotly + NetworkX 资金网络图
│   └── pages/                   # 页面：调度/数据资产/数据接入/图谱/操作台/指标/报告/节点等
├── main.py                      # 命令行入口（--no-report / --check-llm）
├── llms/remote_llm.py           # Ollama 原生 API（生成 / 流式生成 / 健康检查）
├── tools/
│   ├── parse_flow.py            # 自动识别中文流水 / AML 数据集
│   ├── graph_query.py           # 建图、三条规则、环检测、子图查询
│   ├── neo4j_config.py          # Neo4j 连接配置（IP + 端口，兼容旧 NEO4J_URI）
│   ├── dataset_catalog.py       # 数据资产目录（data/new 数据集元数据与抽样状态）
│   ├── data_cleaning.py         # 真实混乱数据画像/映射/流式清洗/pandas 分析
│   └── report_writer.py         # 报告/证据落盘 + 兜底报告
├── agents/                      # parsing / graph / report 智能体
├── supervisor/supervisor_node.py
├── scripts/
│   ├── prepare_datasets.py      # 大数据集确定性抽样（data/prepared）
│   ├── clean_data.py            # 真实数据流式清洗（data/cleaned）
│   ├── evaluate_prepared.py     # 抽样样本规则指标复算（含 IBM 模式覆盖）
│   ├── reset_demo_data.py       # 清理报告/证据/缓存，可选清空 Neo4j
│   ├── evaluate_on_synthetic_aml.py
│   ├── check_llm.py
│   ├── check_neo4j.py           # Neo4j 连接自检（IP + 端口）
│   ├── preflight_check.py
│   ├── generate_sample_data.py
│   ├── open_node1_ports.ps1     # 管理员放行 8501/7474/7687（第二台访问平台与 Neo4j）
│   └── second_node_setup.ps1
├── docs/
│   ├── DATA_CLEANING_GUIDE.md   # 真实混乱数据接入/清洗与答辩口径
│   ├── DATASET_GUIDE.md         # data/new 数据资产使用与赛场展示手册
│   ├── DEMO_SCRIPT.md           # 完整演示步骤（赛前准备→8 分钟流程→故障预案→Q&A）
│   ├── platform_guide.md        # 平台功能与现场演示脚本
│   └── second_node_setup.md     # 第二台 GPU 节点部署手册
├── data/
│   ├── sample_flow.csv          # 100 条演示数据
│   ├── samples/                 # 格式样例（GBK/分号/￥/混合日期等）
│   ├── synthetic_aml/           # 合成 AML 数据集（CC0）
│   ├── new/                     # 5 套公开大数据集原始文件（约 2.5 GB，git 忽略）
│   ├── prepared/                # 抽样样本（生成物，git 忽略）
│   └── cleaned/                 # 清洗产物（生成物，git 忽略）
├── reports/                     # 运行产物（报告 + 证据 + 调度日志，git 忽略）
└── runtime/tasks/               # 任务队列与任务记录（git 忽略）
```

## 5. 数据说明与合规

内置数据：

- `data/synthetic_aml/transactions.csv`：42,175 条交易，金额单位 USD；
- 3,500 个账户，132 个洗钱账户；22 个团伙（12 环形 + 10 集散式）；
- 纯虚构合成数据（CC0-1.0），不含真实公民信息；
- **防标签泄漏**：`is_laundering / laundering_pattern / ring_id` 只在评测脚本读取，
  智能体只看到交易结构，避免“用答案破案”。

`data/new/` 外部大数据集（原始文件约 2.5 GB，不入 Git；现场只用抽样）：

| 数据集 | 原始规模 | 标签 | 演示用途 |
| :--- | ---: | :--- | :--- |
| IBM AML · HI-Small | 507.8 万笔 / 51.5 万账户 | 洗钱 5,177 笔 + 8 类模式 | 真实规模建图、规则迁移与模式覆盖 |
| IBM AML · LI-Small | 692.4 万笔 / 70.5 万账户 | 洗钱 3,565 笔 | 低洗钱率对照 |
| PaySim | 636.3 万笔 | 诈骗 8,213 笔 | 移动支付场景换源验证 |
| Elliptic | 203,769 节点 / 234,355 边 | illicit 4,545 | 图结构 / GNN 扩展方向 |
| IEEE-CIS Fraud | 590,540 笔 / 394 列 | 欺诈 20,663 笔 | 表格模型对照实验 |

生成抽样并现场使用：

```powershell
python scripts/prepare_datasets.py --all        # 约 45 秒，生成 data/prepared/
python scripts/evaluate_prepared.py --dataset ibm-hi-small   # 建图后复算指标
```

详细说明、实测数字与 8 分钟展示脚本见 [docs/DATASET_GUIDE.md](docs/DATASET_GUIDE.md)；
平台“数据资产”页提供同样的目录、抽样、预览与评测入口。

真实混乱数据的接入与清洗（自动识编码/分隔符/列名 → 字段映射 → 流式清洗 → 建图）：

```powershell
python scripts/clean_data.py --input data/new/one/HI-Small_Trans.csv --rows 100000
python scripts/clean_data.py --input data/samples/bank_flow_format_sample.csv --output format_sample_clean
```

详见 [docs/DATA_CLEANING_GUIDE.md](docs/DATA_CLEANING_GUIDE.md)；平台“数据接入”页提供同样的
画像、映射、清洗、进度与 pandas 分析台。

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
python scripts/check_llm.py                   # 检查推理服务（本机/第二台）
python scripts/check_neo4j.py                 # 检查 Neo4j 连接（IP + 端口）
python scripts/preflight_check.py             # 演示前自检
python scripts/evaluate_on_synthetic_aml.py   # 规则评测
python scripts/prepare_datasets.py --all      # 生成 data/new 大数据集抽样（约 45 秒）
python scripts/clean_data.py --input data/new/one/HI-Small_Trans.csv --rows 100000
python scripts/evaluate_prepared.py --dataset ibm-hi-small   # 抽样样本指标复算
python scripts/reset_demo_data.py --all       # 清空图谱/报告/任务/上传/抽样/清洗产物
```

## 8. Node2 接入（当前已接入）

第二台当前信息见 [docs/NETWORK_NODE2.md](docs/NETWORK_NODE2.md)：
IP `192.168.0.200`，模型 `qwen3.5-9b-tools:q4km`，上下文 8192，约 47 tok/s。

一键检测并写入 `.env`：

```powershell
python scripts/connect_node2.py --ip 192.168.0.200 --model qwen3.5-9b-tools:q4km
```

脚本会自动测试 TCP → 读取模型 → 最小推理 → 写入 `.env`（含 `LLM_THINK=false`）。
**Qwen3.5 必须关闭 thinking**：第一台 `.env` 需要 `LLM_THINK=false`，否则 `message.content`
可能为空（思考内容进入 `thinking` 字段）。验证：

```powershell
python scripts/check_llm.py
```

平台“节点与工具”页的 Node2 状态会显示为在线，报告节点调用第二台 GPU 完成。

### 8.1 元智能体自主分析（工具调用实验台）

“元智能体自主分析”页演示真正的工具调用闭环：

1. Node2 Qwen3.5-9B-tools 读取任务和工具清单；
2. 模型自主选择工具（图谱规模 / 归集 / 快进快出 / 账户资金往来 / 证据摘要 / 规则指标）；
3. Node1/Node3 执行工具并把结果回传；
4. 模型根据工具结果继续查或给出“发现 / 证据 / 建议”三段式研判；
5. 页面展示每一轮决策、工具参数、工具结果和最终答案。

当前主任务仍走稳定的固定 Supervisor 流水线；工具调用实验台用于展示升级方向，
下一步可把它接入任务队列和主流程。答辩口径与升级路线见
[docs/defense_notes.md](docs/defense_notes.md)。

## 9. 现场演示（建议 8 分钟）

> **完整逐步操作手册见 [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)**：赛前启动与数据准备、
> 8 分钟标准流程（每步点哪里/看什么/说什么）、5 分钟精简版、分角色操作卡、故障降级预案、
> 评委追问口径、演示后清理，全部按现场可照做的方式写清。

1. **调度总览**：三节点分工、Node2 已接入说明、任务队列状态；
2. **元智能体调度**：提交任务到队列或立即执行，展示阶段卡、日志与报告逐 token 生成；
3. **任务队列**：执行排队任务、查看调用记录与中间结果、任务重跑；
4. **数据资产**：展示 data/new 数据集目录，切 IBM HI-Small / PaySim 抽样再跑一次，
   展示“换数据源不改代码”与抽样评测（详见 [docs/DATASET_GUIDE.md](docs/DATASET_GUIDE.md)）；
5. **数据接入**：现场拿 `data/new` 原始 453 MB IBM 流水（或 `data/samples` 脏数据）走一遍
   自动识别 → 字段映射 → 流式清洗 → 建图，回答“是不是只会用内置数据”的质疑
   （详见 [docs/DATA_CLEANING_GUIDE.md](docs/DATA_CLEANING_GUIDE.md)）；
6. **图数据与工具**：展示 Node3 的图规则结果与资金网络；
7. **规则与指标**：现场重算精确率/召回率与团伙级召回；
8. **研判报告**：打开报告、下载报告与证据；
9. **节点与工具**：展示节点状态、Node2 接入计划、调度日志与断网自检；任务完成后可追加侦查指令。

完整讲解词见 [docs/platform_guide.md](docs/platform_guide.md)；逐步骤操作见
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)。

## 10. 常见问题

| 现象 | 原因 / 解决 |
| :--- | :--- |
| 平台页面为空 | 运行数据已清理；在“元智能体调度”下发任务即可重建 |
| Node2 显示离线 | 检查第二台 Ollama 是否监听 0.0.0.0:11434、防火墙/网络是否变化；跑 `python scripts/connect_node2.py` |
| Node3 显示离线 | Neo4j 未启动，或 `.env` 的 `NEO4J_HOST` / `NEO4J_PORT` 与实际监听不一致；启动 Neo4j 后跑 `python scripts/check_neo4j.py` 验证 |
| 第二台打不开 Neo4j Browser | Neo4j 需 `server.default_listen_address=0.0.0.0` 并重启；第一台管理员运行 `scripts/open_node1_ports.ps1` 放行 7474/7687 |
| AI 报告很慢 | 第二台 GPU 当前约 30 秒；若回退到本机 CPU 调试约 2~4 分钟 |
| 上传大文件失败 | 几百 MB 原始数据不要上传：直接放到 `data/` 下，在“数据接入”页选“服务器文件”；上传限制已放宽到 1 GB（改 `.streamlit/config.toml` 后需重启平台） |
| 数据格式不识别/列名对不上 | 在“数据接入”页手工修正编码/分隔符/表头，并手工选择时间/金额/付款/收款列；复合账号可多选两列 |
| 清洗后建图没有可疑账户 | 检查时间范围/账号映射是否正确；内置数据或 `data/prepared` 抽样更适合快速验证规则命中 |
| 报告 content 为空 | Qwen3.5 必须 `LLM_THINK=false`（`connect_node2.py` 会自动写入） |
| 报告状态 fallback | AI 不可达，自动降级为规则模板报告 |
| 需要重置运行环境 | `python scripts/reset_demo_data.py --all`（清空抽样/清洗产物；保留产物加 `--keep-assets`） |
