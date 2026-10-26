# Node2 局域网 Ollama 接入说明（给调度中心 192.168.0.199）

## 本机信息

| 项 | 值 |
|---|---|
| 主机名 | `DESKTOP-U8E9I1M` |
| WLAN IP | `192.168.0.200/24` |
| 子网掩码 | `255.255.255.0` |
| 网关/热点 | `Hotumnweb`（DHCP，不改成静态） |
| Ollama | `0.40.10` |
| 监听 | `0.0.0.0:11434` / `[::]:11434` |
| GPU | NVIDIA RTX 5060 Laptop GPU，8151 MiB |
| 推荐模型 | `qwen3.5-9b-tools:q4km`（Q4_K_M，`num_ctx=8192`，带 tools） |
| 备用模型 | `qwen3.5:9b` |

## 调度中心要用的地址

```text
http://192.168.0.200:11434
```

不要在调度中心写 `127.0.0.1`，那会指向调度中心自己。

## 最小调用示例

```powershell
$body = @{
  model = 'qwen3.5-9b-tools:q4km'
  messages = @(@{ role = 'user'; content = '只回复四个字：连接正常' })
  stream = $false
  think = $false
  options = @{ num_ctx = 8192; num_predict = 20; temperature = 0 }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Uri http://192.168.0.200:11434/api/chat `
  -Method Post -Body $body -ContentType 'application/json; charset=utf-8' `
  -TimeoutSec 300
```

**关键：Qwen3.5 默认开启 thinking。** 如果调用方不传 `think=false`，
`num_predict` 很小的时候可能只生成思考内容，`message.content` 为空。
第一阶段联调请显式加：

```json
"think": false
```

## 健康检查

```powershell
# 根路径
Invoke-WebRequest http://192.168.0.200:11434/

# 模型列表
Invoke-RestMethod http://192.168.0.200:11434/api/tags
```

## 当前防火墙状态（重要）

- 当前 WLAN 网络配置文件是 **Public**；
- 本机 Public / Private 防火墙当前是 **关闭** 的，所以局域网 IP 实测可以访问；
- `Ollama_Node_11434` 规则 **没有创建**：当前会话不是管理员，
  `New-NetFirewallRule` 返回 `Access is denied`；
- 这属于“能通，但不是最小暴露”的状态。若以后启用 Public 防火墙，
  必须在管理员 PowerShell 补规则（或直接运行
  `scripts\enable_lan_admin.ps1`）：

```powershell
New-NetFirewallRule -DisplayName 'Ollama_Node_11434' -Direction Inbound `
  -Protocol TCP -LocalPort 11434 -Action Allow -Profile Any `
  -RemoteAddress LocalSubnet
```

如果已有同名规则，先删除再创建：

```powershell
Get-NetFirewallRule -DisplayName 'Ollama_Node_11434' -ErrorAction SilentlyContinue |
  Remove-NetFirewallRule
```

如果只想允许调度中心这一台机器，把 `-RemoteAddress LocalSubnet` 换成：

```powershell
-RemoteAddress 192.168.0.199
```

Ollama 本身没有鉴权，11434 暴露在局域网内意味着同网段设备都能调用；更严格的做法是
只允许 `192.168.0.199`，或者把 Ollama 放在受控网段/反向代理后面。

## 如果调度中心连不上

在 `192.168.0.199` 上依次检查：

```powershell
ping 192.168.0.200
Test-NetConnection 192.168.0.200 -Port 11434
```

- ping 不通：检查是否同一个热点、是否开启了“客户端隔离/AP isolation”；
- ping 通但 11434 不通：检查 Node2 的监听地址、Windows 防火墙；
- 能连上但 `content` 为空：加 `think=false`，或把 `num_predict` 调大。

## 本机保持状态

- 已接通电源，AC/DC 睡眠和休眠都设为 0；
- 模型已用 `keep_alive=24h` 预加载；
- 当前由 `ollama serve` 常驻，桌面托盘程序已停止；
- 重启后可用 `scripts\start_ollama_lan.cmd` 重新启动；
- 不要同时再启动 Ollama 桌面程序，避免 11434 端口冲突。

## Qwen-Agent / Node2

`qwen-agent==0.0.34` 已安装在 `D:\jlzxagent\.venv`，但 Node2 FastAPI 当前没有启动，
`8010` 没有监听。第一阶段按调度中心要求只使用 Ollama 的 `/api/chat`；
需要上层 Agent 能力时再启动：

```powershell
cd D:\jlzxagent
scripts\run_node2.cmd
```
