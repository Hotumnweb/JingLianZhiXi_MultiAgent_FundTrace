# 第二台电脑 AI 接入交接提示词

> 用法：把下面「提示词正文」整段复制给第二台电脑上的 AI，让它执行并回报结果。
> 第一台信息：IP `192.168.0.199`（热点网段 `192.168.0.0/24`），平台地址 `http://192.168.0.199:8501`
> 第二台当前 IP：`192.168.0.200`（请以 `ipconfig` 实际结果为准）
> 目标：第一台能通过 `http://<第二台IP>:11434` 调用第二台的 Ollama 模型。

---

## 提示词正文（复制给第二台 AI）

你是第二台 GPU 算力节点上的系统运维 AI。第一台调度中心（IP `192.168.0.199`）已经准备好，
需要通过局域网调用你这台电脑上的 Ollama AI 服务。请你在本机实际执行以下操作，并把结果按模板回报。

### 一、确认网络

1. 输出本机主机名、所有 IPv4 地址、子网掩码；
2. 确认本机 IP 在 `192.168.0.0/24` 网段（预期 `192.168.0.200`）；
3. 执行 `ping 192.168.0.199`，确认能通；
4. 如果 IP 不是 `192.168.0.200`，记录实际 IP，不要强行改静态 IP（热点是 DHCP）。

### 二、确认 Ollama 与模型

1. 执行 `ollama --version`；
2. 执行 `ollama list`，记录**模型完整名称**（第一台需要配置这个名称）；
3. 执行 `nvidia-smi`，记录显卡型号和显存；
4. 如果模型未运行，先用 `ollama run <模型名> "你好"` 做一次本地测试，然后 `/bye` 退出。

### 三、让 Ollama 监听局域网（核心步骤）

1. 设置系统环境变量（需要管理员 PowerShell）：
   ```powershell
   [Environment]::SetEnvironmentVariable('OLLAMA_HOST', '0.0.0.0:11434', 'Machine')
   ```
2. 重启 Ollama：
   ```powershell
   Get-Process | Where-Object { $_.ProcessName -like 'ollama*' } | Stop-Process -Force
   Start-Sleep -Seconds 2
   $env:OLLAMA_HOST = '0.0.0.0:11434'
   Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden
   Start-Sleep -Seconds 5
   ```
   如果你使用的是 Ollama 桌面程序，请退出托盘程序，确认环境变量已写入，再重新启动。
3. 验证监听地址：
   ```powershell
   Get-NetTCPConnection -LocalPort 11434 -State Listen
   ```
   必须看到 `0.0.0.0:11434` 或 `[::]:11434`，不能只有 `127.0.0.1:11434`。

### 四、放行防火墙（只放内网）

以管理员身份执行：

```powershell
New-NetFirewallRule -DisplayName 'Ollama_Node_11434' -Direction Inbound `
  -Protocol TCP -LocalPort 11434 -Action Allow -Profile Any -RemoteAddress LocalSubnet
```

如果已有同名规则，先删除旧规则再创建。不要关闭整个防火墙，不要把 11434 暴露到公网。

### 五、本地验证

1. 浏览器或命令访问 `http://127.0.0.1:11434`，应显示 `Ollama is running`；
2. 读取模型列表：
   ```powershell
   Invoke-RestMethod -Uri http://127.0.0.1:11434/api/tags | ConvertTo-Json -Depth 4
   ```
3. 做一次推理测试（把 `<模型名>` 换成实际模型）：
   ```powershell
   $body = @{
     model = '<模型名>'
     messages = @(@{ role = 'user'; content = '只回复四个字：连接正常' })
     stream = $false
     options = @{ num_predict = 20; temperature = 0 }
   } | ConvertTo-Json -Depth 6
   Invoke-RestMethod -Uri http://127.0.0.1:11434/api/chat -Method Post `
     -Body $body -ContentType 'application/json' -TimeoutSec 300
   ```
   记录回复内容、耗时和 tok/s。

### 六、可选：检查 Qwen-Agent 服务

如果本机已经安装/运行 Qwen-Agent，请报告：
- Qwen-Agent 是否在运行？启动方式是什么？
- 是否暴露了 HTTP 接口或端口？端口号是多少？
- 如果暂时没有对外服务，保持现状即可；第一阶段先用 Ollama 的 `/api/chat` 联调。

### 七、保持环境

- 不要让电脑睡眠/休眠；接通电源；
- 保持连接同一个随身 WiFi 热点；
- 不要修改第一台电脑，不要重装/删除已有模型；
- 完成后保持 Ollama 运行，等待第一台调用。

### 八、按以下模板回报结果

```text
【第二台回报】
主机名：
实际 IP / 子网掩码：
第一台 ping 结果：成功 / 失败
GPU / 显存：
Ollama 版本：
ollama list（完整模型名）：
OLLAMA_HOST 配置：已设置 / 未设置
监听地址（Get-NetTCPConnection）：
防火墙 11434：已放行 / 未放行
本地 API 测试回复：
本地 API 耗时 / tok/s：
Qwen-Agent 状态（可选）：
遇到的问题：
```

请在真实执行后回报，不要只给建议。

---

## 第一台收到回报后的操作

```powershell
conda activate fraud_agent
cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
python scripts/connect_node2.py --ip <第二台实际IP> --model <第二台实际模型名>
```

脚本会自动测试连接、写 `.env`，然后刷新平台查看 Node2 在线并提交任务测试。
