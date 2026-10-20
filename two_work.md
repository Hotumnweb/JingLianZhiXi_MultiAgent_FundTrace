# 第二阶段：GPU Inference Node 实施方案

## 一、第二台电脑的定位与网络规划

**机器配置**：MECHREVO，i7-13700HX，16GB RAM，**NVIDIA GeForce RTX 5060 Laptop GPU（8GB 显存）**。

**定位**：纯粹的算力提供者。只运行 Ollama 服务，不装 Python 环境，不跑数据库，不写业务代码。

### 1. 局域网连接与静态 IP 配置

1. 用一根网线（或通过小交换机）将第一台和第二台电脑连接起来。

2. **不要在第二台上开启无线网络（Wi-Fi），只保留有线网卡（以太网）。**

3. 打开第二台的“网络适配器设置”，找到以太网，配置 IPv4 静态 IP：

   - **IP 地址**：`192.168.50.2`
   - **子网掩码**：`255.255.255.0`
   - **默认网关**：**留空**（重要，确保物理断网）

4. 打开第一台电脑（`192.168.50.1`），按 `Win+R` 输入 `cmd`，执行：

   cmd

   ```
   ping 192.168.50.2
   ```

   

   能通，说明物理局域网建立成功。

### 2. 防火墙放行

在第二台电脑上，我们需要让第一台能访问 Ollama 的 `11434` 端口。

1. 打开“Windows Defender 防火墙” -> 高级设置 -> 入站规则。
2. 新建规则 -> 端口 -> TCP -> 特定本地端口输入 `11434` -> 允许连接 -> 勾选所有网络 -> 命名为 `Ollama_Node`。
3. （或者在开发测试阶段，直接临时关闭第二台电脑的公用网络防火墙）。

------

## 二、第二台电脑安装与配置 Ollama

### 1. 安装 Ollama

1. 访问 `https://ollama.com/download`，下载 Windows 版本的 Ollama。
2. 默认安装即可。

### 2. 配置局域网监听（核心步骤）

默认情况下，Ollama 只允许本机（`127.0.0.1`）访问。必须修改环境变量让它监听局域网。

1. 打开第二台电脑的“系统属性” -> “高级” -> “环境变量”。
2. 在“系统变量”中点击“新建”：
   - **变量名**：`OLLAMA_HOST`
   - **变量值**：`0.0.0.0:11434`
3. 在“系统变量”中找到 `Path`，双击打开，添加 Ollama 的安装路径（通常是 `C:\Users\<你的用户名>\AppData\Local\Programs\Ollama`）。
4. 重启第二台电脑（或者重启 Ollama 服务）。

### 3. 下载并运行模型

打开第二台的 **命令提示符（cmd）**，执行：

cmd

```
ollama run qwen2.5:7b-instruct-q4_K_M
```



> **说明**：你的 RTX 5060 有 8GB 显存。7B 模型的 Q4_K_M 量化版大约占用 5.5GB 显存，留 2.5GB 给系统显示和上下文缓存，这是最稳定、速度最快的配置。下载可能需要几分钟。

下载完成后，你会进入对话界面，随便输入一句话测试，然后输入 `/bye` 退出。Ollama 服务会在后台常驻。

**验证监听是否成功**：在第二台电脑的浏览器访问 `http://localhost:11434`，如果显示 `Ollama is running`，则正常。

------

## 三、第一台电脑的业务代码修改

现在回到第一台电脑（`E:\JingLianZhiXi_MultiAgent_FundTrace`），我们要启用 `report_agent` 并让它调用第二台电脑。

### 1. 修改 `.env` 文件

将原来的 `.env` 修改为（确保指向第二台的 IP）：

env

```
OLLAMA_BASE_URL=http://192.168.50.2:11434/v1/
OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=fraud2026
ENABLE_REPORT_AGENT=1
```



### 2. 修改 `llms/remote_llm.py`

确保代码能读取到正确的 URL：

python

```
import os
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

def get_remote_llm():
    return ChatOpenAI(
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://192.168.50.2:11434/v1/"),
        api_key="ollama", 
        temperature=0.1, # 稍微给一点温度，让报告不那么死板
        max_tokens=2000
    )
```



### 3. 重写 `agents/report_agent.py`（关键业务逻辑）

现在的 `report_agent` 不能只说一句话了，它需要拿到图分析的“强证据”和“弱证据”列表，丢给大模型生成正规的《资金穿透研判报告》。

python

```
import os
from llms.remote_llm import get_remote_llm
from tools.graph_query import find_fast_in_fast_out # 假设你之前写了这个

def report_agent_node(state):
    suspects = state.get("suspicious_accounts", [])
    
    # 将列表转成字符串格式供大模型阅读
    suspect_str = ", ".join(suspects[:30]) # 限制一下长度，防止超出上下文
    
    llm = get_remote_llm()
    
    # 精心设计的 Prompt（提示词），限定大模型的角色和输出格式
    prompt = f"""
    你是一名资深的公安反诈中心资金研判专家。
    我们通过对海量银行流水进行图计算，识别出了以下 {len(suspects)} 个高度可疑的涉案账户（由于篇幅限制，列出前30个）：
    {suspect_str}
    
    已知这些账户触发了以下规则：
    1. 多层归集：资金通过多级账户快速向少数核心账户聚集（符合“水房”特征）。
    2. 环形转账：资金在几个账户之间循环流转，试图制造交易流水或混淆视听。
    3. 快进快出：资金到账后10分钟内即被转移90%以上（符合“卡农”洗钱特征）。
    
    请根据以上信息，撰写一份专业的《涉案资金穿透研判报告》。
    要求：
    1. 语气严肃、专业，符合公安机关公文风格。
    2. 必须包含四个部分：一、资金网络特征分析；二、高风险账户画像；三、侦查建议。
    3. 重点突出“水房”和“卡农”的洗钱逻辑。
    4. 不要编造未提供的具体金额和户名，只基于我给你的规则进行定性分析。
    """
    
    try:
        response = llm.invoke(prompt)
        conclusion = response.content
    except Exception as e:
        conclusion = f"调用远程大模型失败，错误信息：{str(e)}"
    
    return {
        "conclusion": conclusion,
        "logs": state.get("logs", []) + [
            "[ReportAgent] 已获取图分析证据列表",
            "[ReportAgent] 已调用远程 GPU 节点进行大模型研判",
            "[ReportAgent] 报告生成完毕"
        ],
    }
```



### 4. 修改 `supervisor/supervisor_node.py`

确保路由逻辑能走到 `report_agent`：

python

```
import os

def supervisor_node(state):
    logs = state.get("logs", [])
    
    if not state.get("parsed_records"):
        logs.append("[Supervisor] 尚未解析流水 -> 路由到 parsing_agent")
        return {"logs": logs, "next": "parsing_agent"}
        
    if not state.get("suspicious_accounts"): # 假设图分析完会写入这个字段
        logs.append("[Supervisor] 已解析，尚未做图分析 -> 路由到 graph_agent")
        return {"logs": logs, "next": "graph_agent"}
        
    if not state.get("conclusion"):
        if os.getenv("ENABLE_REPORT_AGENT") == "1":
            logs.append("[Supervisor] 图分析完成 -> 路由到 report_agent")
            return {"logs": logs, "next": "report_agent"}
        else:
            logs.append("[Supervisor] 图分析完成；ENABLE_REPORT_AGENT=0（第二台 GPU 节点未就绪），跳过报告节点 -> END")
            return {"logs": logs, "next": "END"}
            
    logs.append("[Supervisor] 报告生成完毕 -> END")
    return {"logs": logs, "next": "END"}
```



------

## 四、执行全链路联调验证

1. **在第二台电脑**：确保 Ollama 服务正在运行（黑窗口或后台服务）。

2. **在第一台电脑**：进入虚拟环境，执行：

   bash

   ```
   python main.py
   ```

   

**预期看到的日志**：

text

```
[Supervisor] 尚未解析流水 -> 路由到 parsing_agent
[ParsingAgent] 解析完成，共 42175 条交易 ...
[Supervisor] 已解析，尚未做图分析 -> 路由到 graph_agent
[GraphAgent] 图分析完成：去重后可疑账户 93 个
[Supervisor] 图分析完成 -> 路由到 report_agent
[ReportAgent] 已调用远程 GPU 节点进行大模型研判
[ReportAgent] 报告生成完毕
=== 研判结论 ===
一、资金网络特征分析
...
二、高风险账户画像
...
```



**如果这一步成功，恭喜你，你的“双机离线多智能体架构”就彻底跑通了！**

------

## 五、现场演示“断网自证”与“性能调优”

1. **拔掉外网**：在第一台和第二台都断开 Wi-Fi 的情况下，你们依然能跑通上述全流程。
2. **速度优化**：如果发现大模型生成报告很慢（超过 2 分钟），可以在第二台电脑上通过任务管理器看 GPU 占用。如果显存爆了（Ollama 跑到 CPU 上了），请更换 `qwen2.5:7b-instruct-q4_0`（更低量化）或者 `qwen2.5:3b`。
3. **Streamlit 展示**：运行 `streamlit run app.py`，把大模型生成的报告用 `st.markdown()` 渲染出来。

------

### 后续接轨第三阶段（Team Ready）

等你把这一步跑通，有了视频和截图，你就可以去组件团队了。团队分工已经非常清晰：

- **A 和 B（网络与算力）**：负责双机局域网的物理搭建、防火墙策略、Ollama 部署。现场演示“断网自证”。
- **C（AI 编排）**：负责现在的这段代码（LangGraph + 图查询 + Prompt 调优）。
- **D（业务与前端）**：负责把 Streamlit 界面做得更炫（比如引入 ECharts 画关系图），并在现场当主讲人。