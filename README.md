# “警链智析”——面向电诈资金图谱的自主协同智能体

> 项目仓库：<https://github.com/Hotumnweb/JingLianZhiXi_MultiAgent_FundTrace>
> 当前版本：**v0.4 集成展示平台版**（第一台电脑：核心调度与编排工作台）
> 参赛方向：新一代信息技术 / 网络安全 / 公安院校特色 + AI 智能体 + 大模型

## 1. 项目一句话

在**断网环境**下，用多智能体自动完成“银行流水解析 → Neo4j 资金图谱构建 → 三类图规则分析 → 本地大模型生成《资金穿透研判报告》”的完整链路，并通过第一台电脑上的**集成展示平台**把智能体调度、图计算证据、检测指标和研判报告完整呈现给评委。

## 2. 第一台电脑：集成展示平台（v0.4 核心交付）

第一台不再只是“跑脚本”，而是一个**深色大屏风格、离线可用**的展示平台（Streamlit + Plotly），把接口、数据、智能体、报告、审计集成在一起：

| 页面 | 展示内容 | 体现的技能点 |
| :--- | :--- | :--- |
| 🛰️ 作战总览 | 六项 KPI、四节点拓扑与健康状态、规则命中分布、证据强度排行、最近研判 | 平台集成、实时健康检查 |
| 🤖 智能体编排 | 选择数据源与侦查指令、启动全链路、**阶段卡片实时点亮、调度日志滚动、报告逐 token 流式输出** | LangGraph 流式编排、实时可视化 |
| 🕸️ 资金图谱 | 从 Neo4j 拉取可疑账户 1 跳子图，Plotly + NetworkX 力导向布局，环形链/归集账户明细 | 图数据库查询、图可视化 |
| 📏 规则与指标 | 三条规则口径、当前命中数量、**现场重算精确率/召回率/团伙级召回** | 规则设计、离线评测 |
| 📄 报告中心 | 历史报告预览、Markdown/证据 JSON 下载、证据明细表 | 报告归档、可复现 |
| 🛡️ 节点与安全 | 四节点状态、本机环境、**外网连通性检测（断网自证）**、接口清单、审计事件流、Wireshark 接入说明 | 安全审计、工程规范 |

**本地实测**：
- 完整流式链路：**892 个 token 事件、7 个节点更新事件**，报告逐字出现在大屏上；
- 本地 CPU（qwen2.5:7b-instruct）：全链路约 **4 分钟**（解析+图分析约 30 秒，报告生成约 3 分钟）；
- Streamlit 六个页面（AppTest）全部加载无异常，真实启动 `HTTP 200`；
- 报告：93 个可疑账户、四段式公安风格报告、金额单位 USD、严格按证据分类引用。

启动平台：

```powershell
conda activate fraud_agent
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
streamlit run app.py
```

## 3. 系统架构（目标四机部署）

```text
Node1 核心调度与编排（本机/平台）   Node2 GPU 推理（Ollama）   Node3 图数据与审计（Neo4j + Wireshark）   Node4 演示汇报（浏览器大屏）
        │                                  │                              │
        ├── LangGraph Supervisor          ├── /api/chat 11434            ├── Bolt 7687
        ├── parsing / graph / report      ├── qwen2.5-7b-instruct        ├── Cypher 规则 + 审计日志
        └── Streamlit 集成展示平台  ──────┴──────────────────────────────┴── 报告中心 / 安全面板
```

当前阶段为**单机联调模式**：第一台同时承载平台、Neo4j，并用本地 Ollama（CPU）模拟 Node2；切换到第二台 GPU 节点只需改 `.env` 两行（见第 7 节）。

## 4. 目录结构

```text
JingLianZhiXi_MultiAgent_FundTrace/
├── app.py                       # 集成展示平台入口（导航 + 主题 + 页面分发）
├── workbench/                   # 平台包（不叫 platform，避免与标准库冲突）
│   ├── theme.py                 # 深色大屏 CSS / KPI 卡 / 节点卡 / 阶段卡
│   ├── services.py              # 节点健康、数据画像、报告索引、审计日志、指标计算
│   ├── runner.py                # 流式编排器（update + custom token 事件）
│   ├── graph_view.py            # Plotly + NetworkX 资金网络图
│   └── pages/                   # 六个页面
├── main.py                      # 命令行入口（--no-report / --check-llm）
├── state.py
├── llms/remote_llm.py           # Ollama 原生 API（生成 + 流式生成 + 健康检查）
├── tools/
│   ├── parse_flow.py            # 自动识别中文流水 / AML 数据集
│   ├── graph_query.py           # 建图、三条规则、环检测、子图查询
│   └── report_writer.py         # 报告/证据落盘 + 兜底报告
├── agents/                      # parsing / graph / report 智能体
├── supervisor/supervisor_node.py
├── scripts/
│   ├── evaluate_on_synthetic_aml.py
│   ├── check_llm.py
│   ├── preflight_check.py
│   ├── generate_sample_data.py
│   └── second_node_setup.ps1
├── docs/
│   ├── platform_guide.md        # 平台页面说明 + 现场演示脚本
│   ├── second_node_setup.md     # 第二台部署手册
│   └── sample_report.md
├── data/
│   ├── sample_flow.csv          # 100 条演示数据
│   └── synthetic_aml/           # 合成 AML 数据集（CC0）
└── reports/                     # 运行产物（报告 + 证据 + 审计，git 忽略）
```

## 5. 数据说明与合规

- `data/synthetic_aml/transactions.csv`：42,175 条交易，2025-01-01 ~ 2025-06-30，金额单位 USD；
- `accounts.csv`：3,500 个账户，132 个洗钱账户；`laundering_rings.csv`：22 个团伙（12 环形 + 10 集散式）；
- 纯虚构合成数据（CC0-1.0），不含真实公民信息，可安全用于比赛演示；
- **防标签泄漏**：`is_laundering / laundering_pattern / ring_id` 只在评测脚本读取，
  智能体只能看到交易结构，避免“用答案破案”；
- 报告与证据自动归档到 `reports/`，便于复核与答辩。

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

## 7. 运行与切换

### 7.1 前置

1. Neo4j 已启动（JDK 17，`localhost:7474` 可登录，密码与 `.env` 一致）；
2. Ollama 已启动且 `ollama list` 有模型（当前为本地 `qwen2.5:7b-instruct`）；
3. Python 环境安装依赖：`pip install -r requirements.txt`（新增 plotly / networkx / psutil）。

### 7.2 常用命令

```powershell
python scripts/check_llm.py              # Ollama 连通性 + 最小推理 + tok/s
python scripts/preflight_check.py       # 演示前一键自检
python main.py                           # 命令行完整链路（含报告）
python main.py --no-report               # 只跑图分析（断网/无模型）
python scripts/evaluate_on_synthetic_aml.py
streamlit run app.py                     # 启动集成展示平台
```

### 7.3 切换第二台 GPU 节点

按 [docs/second_node_setup.md](docs/second_node_setup.md) 配置第二台后，改 `.env`：

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

平台左上角 Node2 状态会自动从“本地 CPU 调试”变为“内网 GPU 节点”。

## 8. 现场演示（建议 5~8 分钟）

1. **总览页**：说清四机分工、当前节点全部在线、22/22 团伙召回；
2. **智能体编排页**：点击“启动全链路”，让评委看阶段卡片点亮、日志滚动、报告逐 token 生成；
3. **资金图谱页**：展示环形链、归集账户和证据强度排行；
4. **规则与指标页**：点“重新计算检测指标”，现场给出精确率/召回率；
5. **报告中心**：打开报告、下载 Markdown/证据 JSON；
6. **节点与安全页**：点“检测外网连通性（断网自证）”，展示审计事件流和接口清单。

详细讲解词与页面说明见 [docs/platform_guide.md](docs/platform_guide.md)。

## 9. 常见问题

| 现象 | 原因 / 解决 |
| :--- | :--- |
| 启动平台报缺少 plotly/networkx | `pip install -r requirements.txt`（已加入依赖清单） |
| Node2 显示离线 | Ollama 未启动或模型名不匹配，跑 `python scripts/check_llm.py` |
| Node3 显示离线 | Neo4j 未启动；按 README 5.1 用 JDK 17 启动 |
| 报告生成很慢 | 正常：本地 CPU 7B 约 2~4 分钟；可先用“仅跑图分析”演示 |
| 报告状态 fallback | 大模型不可达，平台自动降级为规则模板报告 |
| Streamlit 端口占用 | `streamlit run app.py --server.port 8502` |
| 图谱页节点太多 | 关闭“显示关联邻居”，只看强证据账户 |

## 10. 下一步

- 第二台 GPU 节点接入后，实测报告生成耗时并录制演示视频；
- 第三台节点接入 Neo4j 与 Wireshark，替换平台上的“审计事件流”为真实抓包证据；
- 第四台节点接 HDMI 大屏，主讲人按 `docs/platform_guide.md` 的演示脚本走场；
- 增强：元智能体动态路由（按穿透深度决定是否召唤新角色）、话术判别智能体、ECharts 大屏动画。
