## 项目名称：基于多智能体的电诈资金穿透研判系统（第一版）

### 一、第一台电脑的定位与任务边界

机器配置：Lenovo XiaoXinPro 16 IRH8，i7-13620H（10核16线程），16GB RAM，无 NVIDIA 独显。

定位：Coordinator Node（调度中枢）。这台机器不跑大模型，只负责：

运行 LangGraph 编排器（主控调度逻辑）。

运行 Neo4j 图数据库（资金关系网络）。

运行 pandas 流水解析工具。

运行 Streamlit 前端界面。

通过 HTTP 调用第二台机器（GPU Node）的 Ollama 接口。

第一版目标：实现“导入流水 → 解析 → 写入 Neo4j → 调用远程模型生成一句话结论 → 前端展示”的最小闭环。

### 二、环境准备

##### 2.1 安装 Miniconda

下载并安装 Miniconda（Windows x64 版），安装时勾选“Add to PATH”。

安装完成后打开 Anaconda Prompt，执行：

```bash
conda create -n fraud_agent python=3.11 -y
conda activate fraud_agent
```

##### 2.2 创建项目文件夹

在 D 盘（或空间充足的盘）新建文件夹，名称用你的比赛申报项目名，例如：

text

```bash
D:\FraudFundAgent\
```

进入该文件夹：

进入该文件夹：

```bash
cd /d D:\FraudFundAgent
```

##### 2.3 安装依赖

在 fraud_agent 环境中执行：

```bash
pip install langgraph langchain-openai langchain-neo4j neo4j pandas python-dotenv streamlit
```

##### 2.4 安装 Neo4j Community

下载 Neo4j Community Server（Windows 版），解压到 D:\neo4j-community\。

关键配置：编辑 conf/neo4j.conf，确保以下两项：

```conf
dbms.default_listen_address=127.0.0.1
dbms.memory.heap.max_size=2G
```

注意：第一台机器只有 16GB 内存（当时可用约 6.96GB），Neo4j 堆内存不要超过 2GB，否则会卡死。

注意：第一台机器只有 16GB 内存（当时可用约 6.96GB），Neo4j 堆内存不要超过 2GB，否则会卡死。

启动 Neo4j：

```bash
D:\neo4j-community\bin\neo4j.bat console
```

首次启动后，浏览器打开 http://localhost:7474，用默认账号 neo4j / neo4j 登录，修改密码（例如 fraud2026）。记下这个密码。

首次启动后，浏览器打开 http://localhost:7474，用默认账号 neo4j / neo4j 登录，修改密码（例如 fraud2026）。记下这个密码。

### 三、项目目录结构

在 D:\FraudFundAgent\ 下创建以下文件和文件夹：

```text
FraudFundAgent/
├── .env
├── requirements.txt
├── state.py
├── main.py
├── app.py
├── llms/
│   └── remote_llm.py
├── tools/
│   ├── parse_flow.py
│   └── graph_query.py
├── agents/
│   ├── parsing_agent.py
│   └── report_agent.py
├── supervisor/
│   └── supervisor_node.py
└── data/
    └── sample_flow.csv
```



### 四、逐文件实现

##### 4.1 .env（环境变量）

在项目根目录创建 .env：

```env
OLLAMA_BASE_URL=http://192.168.50.2:11434/v1/
OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=fraud2026
```

说明：192.168.50.2 是第二台机器的 IP，第一版如果第二台还没就绪，可以先用 http://localhost:11434/v1/ 占位，等第二台通了再改。

说明：192.168.50.2 是第二台机器的 IP，第一版如果第二台还没就绪，可以先用 http://localhost:11434/v1/ 占位，等第二台通了再改。

##### 4.2 requirements.txt

```text
langgraph
langchain-openai
langchain-neo4j
neo4j
pandas
python-dotenv
streamlit
```



##### 4.3 state.py（共享状态）

```python
from typing import TypedDict, List, Dict, Any

class CaseState(TypedDict):
    instruction: str                # 侦查员输入的指令
    parsed_records: List[Dict]      # 解析后的结构化流水
    suspicious_accounts: List[str]  # 可疑账户列表
    conclusion: str                 # 模型生成的研判结论
    logs: List[str]                 # 执行日志（用于前端展示）
```

##### 4.4 llms/remote_llm.py（远程 Ollama 配置）

```python
import os
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

def get_remote_llm():
    return ChatOpenAI(
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://192.168.50.2:11434/v1/"),
        api_key="ollama",
        temperature=0,
    )
```

验证远程模型是否通（第二台就绪后执行）：

验证远程模型是否通（第二台就绪后执行）：

```python
# test_llm.py（临时测试文件）

from llms.remote_llm import get_remote_llm
llm = get_remote_llm()
print(llm.invoke("返回OK").content)
```

##### 4.5 tools/parse_flow.py（流水解析工具）

```python
import pandas as pd

def parse_flow_file(file_path: str) -> list[dict]:
    df = pd.read_csv(file_path)
    # 统一字段名（根据实际 CSV 列名调整）
    df = df.rename(columns={
        "交易时间": "trade_time",
        "金额": "amount",
        "付款账号": "from_account",
        "收款账号": "to_account",
        "摘要": "summary",
    })
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    return df.to_dict(orient="records")
```

##### 4.6 tools/graph_query.py（Neo4j 工具）

```python
import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

_driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")),
)

def write_transactions(records: list[dict]):
    with _driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")  # 第一版清空重来，后续再改增量
        for r in records:
            session.run(
                """
                MERGE (a:Account {id: $from_acc})
                MERGE (b:Account {id: $to_acc})
                CREATE (a)-[:TRANSFER {amount: $amt, time: $t}]->(b)
                """,
                from_acc=str(r["from_account"]),
                to_acc=str(r["to_account"]),
                amt=r["amount"],
                t=str(r["trade_time"]),
            )

def find_fast_in_fast_out() -> list[str]:
    with _driver.session() as session:
        result = session.run(
            """
            MATCH (a:Account)-[r1:TRANSFER]->(b:Account)-[r2:TRANSFER]->(c:Account)
            WHERE r2.time >= r1.time AND r2.amount > r1.amount * 0.9
            RETURN DISTINCT b.id AS acc
            LIMIT 50
            """
        )
        return [record["acc"] for record in result]
```




##### 4.7 agents/parsing_agent.py（解析智能体）

```python
from tools.parse_flow import parse_flow_file
from tools.graph_query import write_transactions

def parsing_agent_node(state):
    path = "data/sample_flow.csv"
    records = parse_flow_file(path)
    write_transactions(records)
    return {
        "parsed_records": records,
        "logs": state.get("logs", []) + [f"解析完成，共 {len(records)} 条交易，已写入 Neo4j"],
    }
```



##### 4.8 agents/report_agent.py（报告智能体）

```python
from llms.remote_llm import get_remote_llm
from tools.graph_query import find_fast_in_fast_out

def report_agent_node(state):
    suspects = find_fast_in_fast_out()
    llm = get_remote_llm()
    prompt = (
        f"你是一名反诈研判助手。以下是可疑账户列表：{suspects}。"
        f"请用一句话总结这批流水的可疑特征，并给出下一步侦查建议。"
    )
    conclusion = llm.invoke(prompt).content
    return {
        "suspicious_accounts": suspects,
        "conclusion": conclusion,
        "logs": state.get("logs", []) + ["图查询与模型研判完成"],
    }
```

##### 4.9 supervisor/supervisor_node.py（主控调度）

第一版用最简单的条件路由，不让模型决策，避免调试复杂化：

```python
def supervisor_node(state):
    logs = state.get("logs", [])
    if not state.get("parsed_records"):
        logs.append("[Supervisor] 流水未解析，路由到 parsing_agent")
        return {"logs": logs, "next": "parsing_agent"}
    if not state.get("conclusion"):
        logs.append("[Supervisor] 已解析，路由到 report_agent")
        return {"logs": logs, "next": "report_agent"}
    logs.append("[Supervisor] 全部完成，结束")
    return {"logs": logs, "next": "END"}
```

##### 4.10 main.py（LangGraph 入口）

```python
from langgraph.graph import StateGraph, END
from state import CaseState
from supervisor.supervisor_node import supervisor_node
from agents.parsing_agent import parsing_agent_node
from agents.report_agent import report_agent_node

def route(state):
    return state.get("next", "END")

builder = StateGraph(CaseState)
builder.add_node("supervisor", supervisor_node)
builder.add_node("parsing_agent", parsing_agent_node)
builder.add_node("report_agent", report_agent_node)

builder.set_entry_point("supervisor")
builder.add_conditional_edges("supervisor", route, {
    "parsing_agent": "parsing_agent",
    "report_agent": "report_agent",
    "END": END,
})
builder.add_edge("parsing_agent", "supervisor")
builder.add_edge("report_agent", "supervisor")

app = builder.compile()

if __name__ == "__main__":
    result = app.invoke({
        "instruction": "分析这批流水",
        "parsed_records": [],
        "suspicious_accounts": [],
        "conclusion": "",
        "logs": [],
    })
    for log in result["logs"]:
        print(log)
    print("可疑账户：", result["suspicious_accounts"])
    print("研判结论：", result["conclusion"])
```

##### 4.11 app.py（Streamlit 前端）

```python
import streamlit as st
from main import app

st.title("电诈资金穿透研判系统（第一版）")

if st.button("开始分析"):
    with st.spinner("智能体运行中..."):
        result = app.invoke({
            "instruction": "分析这批流水",
            "parsed_records": [],
            "suspicious_accounts": [],
            "conclusion": "",
            "logs": [],
        })
    st.subheader("执行日志")
    for log in result["logs"]:
        st.write(log)
    st.subheader("可疑账户")
    st.write(result["suspicious_accounts"])
    st.subheader("研判结论")
    st.write(result["conclusion"])
```

### 五、测试数据准备

##### 5.1 生成模拟流水

在 data/ 下创建 sample_flow.csv。如果暂时没有真实数据，先手动构造 10 条测试数据，格式如下：

```csv
交易时间,金额,付款账号,收款账号,摘要
2025-01-01 10:00:00,10000,A001,B001,转账
2025-01-01 10:05:00,9500,B001,C001,转账
2025-01-01 10:10:00,9000,C001,D001,转账
2025-01-01 11:00:00,5000,E001,F001,刷单返利
2025-01-01 11:05:00,4800,F001,G001,刷单返利
2025-01-01 12:00:00,20000,H001,I001,投资理财
2025-01-01 12:10:00,19000,I001,J001,投资理财
2025-01-01 12:20:00,18000,J001,K001,投资理财
2025-01-01 13:00:00,3000,L001,M001,冒充公检法
2025-01-01 13:05:00,2900,M001,N001,冒充公检法
```

##### 5.2 验证解析

在 fraud_agent 环境中执行：

5.2 验证解析
在 fraud_agent 环境中执行：

```bash
python main.py
```

预期输出：

预期输出：

日志显示“解析完成，共 10 条交易，已写入 Neo4j”

日志显示“图查询与模型研判完成”

可疑账户列表非空（B001、C001、F001、I001、J001、M001 等可能被识别）

研判结论是一句模型生成的话

### 六、执行顺序清单（照此逐项打勾）

步骤	操作	验证方式
1	安装 Miniconda，创建 fraud_agent 环境	conda activate fraud_agent 成功
2	创建项目文件夹，安装 pip 依赖	pip list 能看到 langgraph、neo4j、pandas
3	安装 Neo4j，修改 heap 为 2G，启动	浏览器访问 localhost:7474 能登录
4	创建目录结构和 .env	文件齐全，密码与 Neo4j 一致
5	放入 sample_flow.csv	10 条数据
6	在 main.py 中先注释掉 report_agent，只跑 parsing_agent	日志显示写入 Neo4j 成功，MATCH (n) RETURN count(n) 在 Neo4j 浏览器里能看到节点
7	恢复 report_agent，第二台 Ollama 就绪后跑全链路	python main.py 输出可疑账户和结论
8	启动前端	streamlit run app.py，点击按钮能展示结果

### 七、第一版必须避开的三个坑

Neo4j 内存：dbms.memory.heap.max_size 绝对不能超过 2G，否则 16GB 内存的机器会卡死。

Ollama 地址：第一版如果第二台没就绪，report_agent 会报连接错误。先单独跑通 parsing_agent，把图数据库链路验证完，再等第二台。

CSV 列名：parse_flow.py 里的 rename 映射必须与你实际 CSV 的列名一致，否则 KeyError。如果列名不同，先改映射再运行。

### 八、第一版跑通后的下一步

第一版只证明了“数据进 → 图查询 → 模型出结论 → 前端展示”这条链路是通的。下一步再考虑：

让 supervisor 真正调用模型做路由决策（而不是现在的 if-else）。

把 report_agent 拆成“话术判别”和“报告生成”两个智能体。

加入第二台机器的跨机调用验证（curl 通后再改 .env）。