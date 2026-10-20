# “警链智析”——面向电诈资金图谱的自主协同智能体（v0.2）

> 项目目录：`E:\JingLianZhiXi_MultiAgent_FundTrace`
> 当前版本：v0.2 —— 接入合成 AML 数据集（42,175 条交易 / 3,500 账户 / 22 个洗钱团伙）
> 第二台 GPU 节点仍未就绪，报告节点通过 `.env` 开关占位。

## 1. 这一版做什么

```text
读取流水 CSV（pandas，自动识别两种数据格式）
        ↓
解析成统一字段（时间 ISO 化、丢弃答案标签、清洗脏数据）
        ↓
写入 Neo4j（账户 = 节点，转账 = 边，Account 上记录 tx_count）
        ↓
账户关联智能体（三条图规则）：
  ① 多层归集（强证据）    ② 环形转账（强证据）    ③ 快进快出（辅助证据）
        ↓
报告智能体（可选，需要第二台 Ollama）：把结构化证据写成研判结论
        ↓
Streamlit 前端展示：执行日志 / 可疑账户 / 研判结论
```

**v0.2 新增**：
- 支持 `data/synthetic_aml` 合成 AML 数据集，字段自动识别，无需改代码；
- 新增 `graph_agent`（账户关联智能体），**断网、无大模型时也能独立产出可疑账户**；
- 三类图规则 + 离线评测脚本（精确率/召回率/团伙命中率可直接写进答辩材料）；
- 修复 label leakage：数据集的 `is_laundering / laundering_pattern / ring_id` 不进入智能体输入。

## 2. 数据集

| 文件 | 说明 |
| :--- | :--- |
| `data/synthetic_aml/transactions.csv` | 42,175 条交易，时间范围 2025-01-01 ~ 2025-06-30 |
| `data/synthetic_aml/accounts.csv` | 3,500 个账户，132 个被标记为洗钱账户（`is_synthetic_mule`） |
| `data/synthetic_aml/laundering_rings.csv` | 22 个洗钱团伙：12 个 Circular Loop + 10 个 Fan-Out Fan-In Smurfing |
| `data/synthetic_aml/data_dictionary.json` | 字段字典 |
| `data/sample_flow.csv` | 第一版 100 条自造演示数据（保留，用于快速演示） |

该数据集为纯虚构合成数据（CC0-1.0），不含真实公民信息，可安全用于比赛演示。
**标签使用原则**：智能体只读交易结构（时间、金额、收付款账号），
`is_laundering / laundering_pattern / ring_id` 只在评测脚本里读，避免“用答案破案”。

## 3. 目录结构

```text
JingLianZhiXi_MultiAgent_FundTrace/
├── .env
├── .gitignore
├── README.md
├── requirements.txt
├── state.py                       # 共享状态 CaseState（含 evidence 字段）
├── main.py                        # LangGraph 入口：supervisor / parsing / graph / report
├── app.py                         # Streamlit 前端
├── llms/
│   └── remote_llm.py              # 远程 Ollama 接入层
├── tools/
│   ├── parse_flow.py              # 流水解析（自动识别中文流水 / AML 数据集）
│   └── graph_query.py             # Neo4j 写入 + 三条图规则 + 环检测
├── agents/
│   ├── parsing_agent.py           # 解析智能体（解析 + 建图）
│   ├── graph_agent.py             # 账户关联智能体（三条图规则）
│   └── report_agent.py            # 报告智能体（证据 -> 大模型结论）
├── supervisor/
│   └── supervisor_node.py         # 主控调度（确定性路由）
├── scripts/
│   ├── generate_sample_data.py    # 生成 100 条演示数据（固定种子）
│   └── evaluate_on_synthetic_aml.py  # 在 AML 数据集上评测检测效果
└── data/
    ├── sample_flow.csv            # 100 条演示数据
    └── synthetic_aml/             # 合成 AML 数据集
```

## 4. 三条图规则与实测效果

| 规则 | 判定条件 | 定位 |
| :--- | :--- | :--- |
| 多层归集（Fan-In） | 24 小时内 ≥4 个不同上游账户汇入，金额离散系数 CV ≤ 0.15 | 强证据 |
| 环形转账（Circular Loop） | 3~6 跳闭环，时间严格递增，每跳金额为上一跳的 90%~110%，跨度 ≤ 7 天 | 强证据 |
| 快进快出（Pass-through） | 48 小时内转出 ≥ 95% 收款金额，且账户总交易笔数 ≤ 8（卡农特征） | 辅助证据 |

在 22 个洗钱团伙、132 个洗钱账户的数据集上实测：

| 指标 | 结果 |
| :--- | :--- |
| 强证据合并（归集 + 环形） | 61 个账户，61 个命中，精确率 **1.000**，召回率 0.462，F1 0.632 |
| 强证据 + 辅助证据（最终可疑清单） | 93 个账户，76 个命中，精确率 **0.817**，召回率 0.576，F1 0.676 |
| 团伙级召回 | **22/22** 个洗钱团伙至少命中了 1 个账户 |

复现评测：

```powershell
python scripts/evaluate_on_synthetic_aml.py
```

## 5. 运行前置

### 5.1 启动 Neo4j

安装位置：`D:\softwaredata\neo4j-community`（Neo4j 5.26.25）。
已配置：`server.default_listen_address=127.0.0.1`、`server.memory.heap.max_size=2g`、pagecache 1g。

Neo4j 5 需要 JDK 17，而系统 `JAVA_HOME` 默认指向 JDK 8，启动前先临时切到 JDK 17：

```powershell
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot"
Set-Location "D:\softwaredata\neo4j-community"
.\bin\neo4j.bat console
```

保持窗口不关，浏览器打开 <http://localhost:7474>，用 `neo4j / fraud2026` 登录
（密码必须与 `.env` 的 `NEO4J_PASSWORD` 一致）。

### 5.2 Python 环境

```powershell
conda activate fraud_agent
Set-Location "E:\JingLianZhiXi_MultiAgent_FundTrace"
where.exe python    # 应指向 C:\Users\Hotumn\.conda\envs\fraud_agent\python.exe
```

## 6. 运行方式

```powershell
# 1) 跑合成 AML 数据集（默认，4.2 万条，首次约 30 秒）
python main.py

# 2) 跑第一版 100 条演示数据（切换数据源只需传路径）
python main.py data/sample_flow.csv

# 3) 评测三条图规则（需要先跑过 main.py 建图）
python scripts/evaluate_on_synthetic_aml.py

# 4) 启动前端（第二台就绪前后都可以用，报告节点会自动跳过）
streamlit run app.py
```

预期输出（AML 数据集）：

```text
[ParsingAgent] 解析完成，共 42175 条交易
[ParsingAgent] 已写入 Neo4j：42175 条转账边；当前图谱共 3492 个账户、42175 条边
[GraphAgent] 图分析完成：归集账户 10 个，环形转账链 12 条（覆盖 51 个账户），
             快进快出账户 37 个；强证据账户 61 个，去重后可疑账户 93 个
[Supervisor] 图分析完成；ENABLE_REPORT_AGENT=0，跳过报告节点 -> END
```

Neo4j Browser 验证：

```cypher
MATCH (n:Account) RETURN count(n);            // 3492
MATCH ()-[r:TRANSFER]->() RETURN count(r);    // 42175
MATCH p=(a:Account)-[r:TRANSFER]->(b:Account) RETURN p LIMIT 50;
```

## 7. 第二台未就绪时的占位约定

- `.env` 中 `ENABLE_REPORT_AGENT=0`：supervisor 跳过报告节点，但 graph_agent 仍会输出可疑账户。
- `.env` 中 `OLLAMA_BASE_URL` 先按现场规划写 `http://192.168.50.2:11434/v1/`。
- 第二台装好 Ollama 后：先在第二台启动 `OLLAMA_HOST=0.0.0.0:11434` 并拉取
  `qwen2.5:7b-instruct-q4_K_M`，第一台 `curl http://第二台IP:11434/v1/models` 通了，
  再把 `.env` 的 IP 改成实际地址、`ENABLE_REPORT_AGENT=1`，重跑 `python main.py` 即可生成研判结论。

## 8. 常见问题

| 现象 | 原因 / 解决 |
| :--- | :--- |
| `RuntimeError: dictionary changed size during iteration` | v0.2 已修复（环检测时 defaultdict 访问问题） |
| `ClientError: Cannot merge ... id: null` 或 `Expected parameter` | v0.2 已修复（批量写入参数嵌套错误） |
| `FileNotFoundError: data/synthetic_aml/transactions.csv` | 数据集文件缺失，检查路径是否放对 |
| 首次建图较慢（约 20~30 秒） | 正常：4.2 万条边写入 + 自动建 `Account(id)` 唯一约束 |
| `streamlit run app.py` 端口被占用 | 换端口：`streamlit run app.py --server.port 8502` |
| 修改 `.env` 后没生效 | 从项目根目录启动程序；改完重启进程 |
| Neo4j 启动报 Java 版本不支持 | 按 5.1 先设置 `$env:JAVA_HOME` 到 JDK 17 |
