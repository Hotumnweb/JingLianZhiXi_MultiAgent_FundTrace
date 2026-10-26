# 第二阶段：GPU Inference Node 部署手册（v0.7）

> 说明：本文是比赛现场固定内网（静态 IP、默认网关留空）的正式部署方案。
> 当前双机联调的实际状态（随身 WiFi、Qwen3.5-9B-tools、think=false）见
> [NETWORK_NODE2.md](NETWORK_NODE2.md)；两套方案代码一致，只改 `.env`。

> 适用场景：第二台电脑（MECHREVO / i7-13700HX / 16GB / RTX 5060 Laptop 8GB）

---

## 一、网络配置（物理断网演示的关键）

### 1.1 硬件连接

- 在第一台、第二台之间接一根千兆网线（或通过小交换机连接）；
- 第二台**关闭 Wi-Fi**，只保留有线网卡；
- 两台电脑都不设默认网关，确保“物理隔离、数据不出局”。

### 1.2 静态 IP

| 机器 | 角色 | IP | 子网掩码 | 默认网关 | DNS |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 第一台 | Coordinator Node | `192.168.50.1` | `255.255.255.0` | 留空 | 留空 |
| 第二台 | GPU Inference Node | `192.168.50.2` | `255.255.255.0` | 留空 | 留空 |

Windows 设置路径：`设置 → 网络和 Internet → 以太网 → IP 分配 → 编辑 → 手动 → IPv4`。

### 1.3 连通性验证

第一台执行：

```powershell
ping 192.168.50.2
ping 8.8.8.8        # 预期：请求超时（说明外网已断）
```

能 ping 通第二台、ping 不通外网，就满足比赛现场“断网自证”的要求。

---

## 二、Ollama 安装与配置

### 2.1 安装

1. 访问 <https://ollama.com/download> 下载 Windows 版并默认安装；
2. 确认 `ollama --version` 能正常输出版本号；
3. 推荐把模型目录放到空间充足的磁盘（可选）：

```powershell
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS', 'D:\ollama-models', 'Machine')
```

### 2.2 允许局域网访问（核心）

Ollama 默认只监听 `127.0.0.1`。必须设置：

```powershell
[Environment]::SetEnvironmentVariable('OLLAMA_HOST', '0.0.0.0:11434', 'Machine')
```

然后**重启 Ollama**（退出托盘程序后重新启动，或重启电脑）。

### 2.3 防火墙放行

```powershell
New-NetFirewallRule -DisplayName 'Ollama_Node_11434' -Direction Inbound `
  -Protocol TCP -LocalPort 11434 -Action Allow -Profile Any
```

或者直接运行一键脚本（管理员 PowerShell）：

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\second_node_setup.ps1
```

### 2.4 拉取基座模型并微调

```powershell
ollama pull qwen3:4b
ollama list
```

- `qwen3:4b` 是基座模型，后续用资金分析数据微调（LoRA/QLoRA），导出 GGUF 后通过
  `ollama create qwen3-4b-fraud -f Modelfile` 导入为自定义模型；
- 微调后的模型名以 `ollama list` 为准，第一台 `.env` 的 `OLLAMA_MODEL` 要填这个名称；
- **Qwen-Agent 运行在第二台**：它负责接收第一台下发的任务、拆解任务、多轮调用工具并汇总结果，
  第一台不需要安装 Qwen-Agent，只通过 HTTP 调用第二台的 Ollama 接口。

模型名以 `ollama list` 的实际输出为准；若拉取或导入的是别的 tag，请同步修改第一台 `.env` 里的 `OLLAMA_MODEL`。

---

## 三、第二台自检

```powershell
# 1) 服务是否监听所有网卡
Get-NetTCPConnection -LocalPort 11434 -State Listen

# 2) 本地访问
curl http://127.0.0.1:11434

# 3) 显卡是否被 Ollama 使用（发一次请求后看 PROCESSOR 一列应为 GPU）
ollama run qwen3:4b "你好"
ollama ps
```

`ollama ps` 正常应显示 `PROCESSOR` 为 `100% GPU`，`SIZE` 约 3~4GB（Qwen3-4B 量化后）。
如果显示 `100% CPU`，说明显存不够或驱动异常，需要检查 `nvidia-smi` 和驱动版本。

---

## 四、第一台切换到大模型（远程模式）

### 4.1 先验证链路

```powershell
conda activate fraud_agent
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace

$env:OLLAMA_BASE_URL = 'http://192.168.50.2:11434'
$env:OLLAMA_MODEL = '你的Qwen3-4B微调模型名'
python scripts/check_llm.py
```

看到“回复：连接正常”以及 tok/s 数据，说明第二台就绪。

### 4.2 修改 `.env`

```env
OLLAMA_BASE_URL=http://192.168.50.2:11434
OLLAMA_MODEL=你的Qwen3-4B微调模型名
ENABLE_REPORT_AGENT=1
```

### 4.3 跑完整链路

```powershell
python main.py
```

预期日志：

```text
[GraphAgent] 图分析完成：归集账户 10 个，环形转账链 12 条 ... 可疑账户 93 个
[ReportAgent] 正在调用 Ollama 生成研判报告（本地 CPU 约需 2~4 分钟）……
[ReportAgent] 大模型完成：耗时 X 秒，生成 X tokens，速度 X tok/s
[ReportAgent] 研判报告已落盘：reports/xxxx_report.md
```

报告与证据分别保存在 `reports/` 目录，可直接用于答辩截图。

---

## 五、现场演示检查清单

1. 第二台：`ollama list` 有模型；`ollama ps` 显示 GPU；`http://localhost:11434` 正常；
2. 第一台：Neo4j 已启动（`neo4j.bat console` 窗口在，`localhost:7474` 可登录）；
3. 第一台：`python scripts/preflight_check.py` 全部 OK；
4. 断网自证：拔掉外网 / 关闭 Wi-Fi，`ping 8.8.8.8` 不通，`ping 192.168.50.2` 通；
5. 运行 `streamlit run app.py`，展示：图分析证据 → 可疑账户 → 大模型研判报告 → 下载报告；
6. 备用方案：如果 GPU 节点临时故障，把 `.env` 改回本机 `127.0.0.1` 走本地模型，
   或在平台勾选“仅执行图工具分析（不调用 AI）”，系统仍能输出图分析结果。

---

## 六、“本地先行”与 Node2 目标状态

- **Node2 目标形态**：Qwen3-4B 基座 + 资金分析数据微调 + Qwen-Agent + Ollama，
  元智能体运行在 Node2，第一台通过 HTTP 多轮调用；
- **开发调试现状**：第二台到货前，第一台用本地 Ollama（CPU）跑通全链路：
  - 模型：`qwen2.5:7b-instruct`（Q4_K_M，4.7GB）存放在 `E:\models`；
  - 服务：`OLLAMA_HOST=0.0.0.0`，第一台本地 `http://127.0.0.1:11434`；
  - CPU 推理约 **9~13 tok/s**，生成一份报告约 **2~4 分钟**；
- 本地模式与远程模式代码完全一致，Node2 接入后只改 `.env` 两行；
- 平台“节点与工具”页会把 Node2 显示为“占位”，接入成功后自动变为“在线”。

**为什么先做本地跑通**：第二台到货后网络/防火墙/模型环境都可能需要调试，
先把业务链路和报告生成逻辑在本地验证完，第二台只需要替换地址，风险最低。
