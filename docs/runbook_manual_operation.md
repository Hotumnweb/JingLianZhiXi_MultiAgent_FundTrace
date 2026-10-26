# 第一台调度中心 · 从零操作手册

> 当前状态（2026-10-26）：
> - 第一台：`192.168.0.199`（随身 WiFi `Hotumnweb`，网段 `192.168.0.0/24`）
> - 第二台：`192.168.0.200`，模型 `qwen3.5-9b-tools:q4km`，Ollama 监听 `0.0.0.0:11434`
> - 第一台平台与 Neo4j **已停止**；报告、证据、任务记录、图谱、缓存**已清空**
> - 代码、数据集、`.env`、模型、Git 仓库**保留**

---

## 一、清空步骤（以后想重新来一遍时照做）

### 1.1 一键清空（推荐）

清空图谱需要 Neo4j 先启动：

```powershell
# 1) 启动 Neo4j（保持窗口不关）
D:\softwaredata\neo4j-community\start-neo4j.bat

# 2) 回到项目目录，清空报告/任务/缓存/图谱
conda activate fraud_agent
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
python scripts\reset_demo_data.py --graph
```

脚本会清理：`reports/` 报告与证据、`runtime/tasks/` 任务记录、`__pycache__`、
`*.pyc`、`.ipynb_checkpoints`，并清空 Neo4j 图谱。

### 1.2 手动清空（不用脚本时）

```powershell
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace

# 报告 / 证据 / 调度日志
Remove-Item .\reports\* -Recurse -Force -ErrorAction SilentlyContinue

# 任务队列
Remove-Item .\runtime\tasks\* -Recurse -Force -ErrorAction SilentlyContinue

# Python 缓存
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -File -Filter *.pyc | Remove-Item -Force -ErrorAction SilentlyContinue
```

清空 Neo4j 图谱（浏览器 <http://localhost:7474> 执行）：

```cypher
MATCH (n) DETACH DELETE n;
```

### 1.3 停止第一台服务

- 平台：切换到运行 `streamlit run app.py` 的终端，按 `Ctrl+C`；
- Neo4j：切换到 `start-neo4j.bat` 的窗口，按 `Ctrl+C`；
- 不要用任务管理器乱杀 Java 进程，避免数据库非正常关闭。

### 1.4 确认清空结果

```powershell
(Get-ChildItem .\reports -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count   # 0
(Get-ChildItem .\runtime\tasks -File -ErrorAction SilentlyContinue | Measure-Object).Count       # 0
Get-NetTCPConnection -LocalPort 8501,7474,7687 -State Listen -ErrorAction SilentlyContinue         # 无输出
```

---

## 二、从零启动（第一台）

### 2.1 启动 Neo4j（Node3 工具与图数据）

```powershell
D:\softwaredata\neo4j-community\start-neo4j.bat
```

- 看到 `Started.` 且窗口保持不关；
- 浏览器打开 <http://localhost:7474>，账号 `neo4j`，密码 `fraud2026`；
- 执行 `RETURN 1;` 能返回结果，说明图数据库正常。

### 2.2 确认第二台 AI（Node2）在线

第二台需要保持：
- Ollama 监听 `0.0.0.0:11434`；
- 模型 `qwen3.5-9b-tools:q4km`；
- 电脑不睡眠、连接同一随身 WiFi。

在第一台执行：

```powershell
conda activate fraud_agent
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace

# 1) 先看网络
ping 192.168.0.200
Test-NetConnection 192.168.0.200 -Port 11434

# 2) 检查模型和推理
python scripts\check_llm.py
```

预期看到 `服务检查通过`、回复 `连接正常`、约 40~50 tok/s。

如果第二台 IP 变了或连接失败：

```powershell
# 先到第二台执行 ipconfig 查实际 IP
python scripts\connect_node2.py --ip 第二台实际IP --model qwen3.5-9b-tools:q4km
```

### 2.3 启动平台

```powershell
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
streamlit run app.py
```

浏览器访问：<http://localhost:8501>（第二台访问用 `http://192.168.0.199:8501`）。

如果第二台打不开平台，在第一台用**管理员 PowerShell** 放行端口：

```powershell
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
powershell -ExecutionPolicy Bypass -File scripts\open_node1_ports.ps1
```

### 2.4 检查平台节点状态

打开“节点与工具”或左侧栏：

- Node1 调度中心：在线；
- Node2 GPU 算力中心：在线，模型 `qwen3.5-9b-tools:q4km`；
- Node3 工具与图数据：在线，若图谱为空显示 `0 账户 / 0 转账`。

---

## 三、亲手跑一次完整任务

### 3.1 页面操作顺序

1. 打开“**元智能体调度**”；
2. 数据源选择 `data/synthetic_aml/transactions.csv`（42,175 条）；
3. 打开“执行 AI 研判报告”；
4. 二选一：
   - **立即执行任务**：马上跑；
   - **提交到任务队列**：到“任务队列”页点“执行队列”；
5. 等待执行，观察：
   - 阶段卡：主控调度 → 流水解析 → 账户关联 → 研判报告；
   - 调度日志滚动；
   - 报告逐 token 出现在右侧；
6. 完成后查看结果：
   - 可疑账户 93 个；归集 10；环形链 12；快进快出 37；
   - 报告状态“AI 生成”，报告约 30 秒；
7. 到“**任务队列**”查看任务记录、调度步骤、Node1/Node2/Node3 调用记录与中间结果；
8. 到“**图数据与工具**”查看资金网络图、环形链、归集账户；
9. 到“**规则与指标**”点“重新计算检测指标”，确认精确率/召回率；
10. 到“**研判报告**”预览并下载报告与证据 JSON；
11. 回到任务详情，展开“**追加侦查指令**”，输入例如：
    `重点说明环形转账链的资金闭环特征`
    观察第二台 AI 返回补充分析；
12. 到“**节点与工具**”展示三节点状态、调度日志、外网隔离检测。

### 3.2 命令行验证（可选）

```powershell
python main.py                        # 完整链路（含第二台 AI 报告）
python main.py --no-report            # 只跑图工具分析
python scripts\evaluate_on_synthetic_aml.py   # 规则评测
python scripts\preflight_check.py     # 演示前自检
```

---

## 四、关闭与恢复干净环境

```powershell
# 1) 关闭平台：streamlit 终端 Ctrl+C
# 2) 关闭 Neo4j：start-neo4j.bat 窗口 Ctrl+C
# 3) 清空数据与缓存（Neo4j 启动状态下才能清图谱）
python scripts\reset_demo_data.py --graph
# 4) 再关闭 Neo4j
```

---

## 五、常见问题

| 现象 | 处理 |
| :--- | :--- |
| Node2 显示离线 | 第二台 Ollama 是否监听 `0.0.0.0:11434`；第二台 IP 是否变化；防火墙是否拦截 |
| `check_llm.py` 报连不上 | 先 `ping 192.168.0.200`，再 `Test-NetConnection 192.168.0.200 -Port 11434`；必要时重跑 `connect_node2.py` |
| AI 返回 content 为空 | Qwen3.5 必须 `LLM_THINK=false`；重新运行 `connect_node2.py` 会自动写入 |
| Neo4j 启动报 Java 版本 | 使用 `start-neo4j.bat`（内部已设置 JDK17） |
| 平台 8501 被占用 | `streamlit run app.py --server.port 8502` |
| 第二台访问不了平台 | 第一台管理员运行 `scripts\open_node1_ports.ps1` |
| 想验证外网是否断开 | 平台“节点与工具”点“外网隔离检测” |

---

## 六、关键位置

| 内容 | 路径 |
| :--- | :--- |
| 平台入口 | `app.py` |
| 平台页面 | `workbench/pages/` |
| 调度执行/任务队列 | `workbench/coordinator.py`、`workbench/tasks.py` |
| 报告与证据 | `reports/`（运行时自动生成） |
| 任务记录 | `runtime/tasks/`（运行时自动生成） |
| 第二台接入脚本 | `scripts/connect_node2.py` |
| 第二台说明 | `docs/NETWORK_NODE2.md` |
| 平台使用/演示稿 | `docs/platform_guide.md` |
| 配置模板 | `.env.example`（实际配置在 `.env`，不提交 Git） |
