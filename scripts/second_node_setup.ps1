# 警链智析 · 第二台 GPU 节点一键配置脚本
# 用法：在第二台电脑上，以【管理员身份】打开 PowerShell，执行：
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\scripts\second_node_setup.ps1
#
# 脚本会做 5 件事：
#   1. 检查 NVIDIA 显卡驱动（nvidia-smi）
#   2. 设置系统环境变量 OLLAMA_HOST=0.0.0.0:11434（允许第一台访问）
#   3. 开放 Windows 防火墙入站 TCP 11434
#   4. 重启 Ollama 服务
#   5. 拉取 qwen2.5:7b-instruct-q4_K_M 模型
#
# 注意：本脚本不负责配置静态 IP（网络适配器名称因机器而异），
#       请按 docs/second_node_setup.md 的“一、网络配置”手动设置。

$ErrorActionPreference = 'Continue'

Write-Host '========================================' -ForegroundColor Cyan
Write-Host ' 警链智析 · 第二台 GPU 节点一键配置' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan

# ---------- 1. 显卡检查 ----------
Write-Host ''
Write-Host '[1/5] 检查 NVIDIA 显卡与驱动...' -ForegroundColor Yellow
try {
    nvidia-smi
    Write-Host '      显卡驱动正常（请确认显存 ≥ 8GB）' -ForegroundColor Green
} catch {
    Write-Host '      [警告] 未检测到 nvidia-smi，请先安装 NVIDIA 显卡驱动！' -ForegroundColor Red
}

# ---------- 2. OLLAMA_HOST ----------
Write-Host ''
Write-Host '[2/5] 设置系统环境变量 OLLAMA_HOST=0.0.0.0:11434 ...' -ForegroundColor Yellow
[Environment]::SetEnvironmentVariable('OLLAMA_HOST', '0.0.0.0:11434', 'Machine')
$env:OLLAMA_HOST = '0.0.0.0:11434'
Write-Host '      已写入系统环境变量（对重启后的 Ollama 生效）' -ForegroundColor Green

# ---------- 3. 防火墙 ----------
Write-Host ''
Write-Host '[3/5] 开放防火墙入站 TCP 11434 ...' -ForegroundColor Yellow
$ruleName = 'Ollama_Node_11434'
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP `
        -LocalPort 11434 -Action Allow -Profile Any | Out-Null
    Write-Host '      已创建入站规则 Ollama_Node_11434' -ForegroundColor Green
} else {
    Write-Host '      入站规则已存在，跳过' -ForegroundColor Green
}

# ---------- 4. 重启 Ollama ----------
Write-Host ''
Write-Host '[4/5] 重启 Ollama 服务 ...' -ForegroundColor Yellow
Get-Process -Name 'ollama', 'ollama app' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCommand) {
    Write-Host '      [错误] 找不到 ollama 命令，请先安装 Ollama 并加入 PATH' -ForegroundColor Red
    exit 1
}
Start-Process -FilePath $ollamaCommand.Source -ArgumentList 'serve' -WindowStyle Hidden
Start-Sleep -Seconds 5
Write-Host '      已在后台启动 ollama serve（监听 0.0.0.0:11434）' -ForegroundColor Green

# ---------- 5. 拉取模型 ----------
Write-Host ''
Write-Host '[5/5] 拉取模型 qwen2.5:7b-instruct-q4_K_M（约 4.7GB，请耐心等待）...' -ForegroundColor Yellow
& $ollamaCommand.Source pull qwen2.5:7b-instruct-q4_K_M
if ($LASTEXITCODE -ne 0) {
    Write-Host '      [警告] 模型拉取失败，请检查网络后重新执行 ollama pull' -ForegroundColor Red
} else {
    Write-Host '      模型拉取完成' -ForegroundColor Green
}

Write-Host ''
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ' 第二台节点配置完成，接下来：' -ForegroundColor Cyan
Write-Host ' 1) 浏览器访问 http://localhost:11434，应显示 Ollama is running' -ForegroundColor White
Write-Host ' 2) 在第一台电脑验证：' -ForegroundColor White
Write-Host '    $env:OLLAMA_BASE_URL="http://192.168.50.2:11434"' -ForegroundColor Gray
Write-Host '    $env:OLLAMA_MODEL="qwen2.5:7b-instruct-q4_K_M"' -ForegroundColor Gray
Write-Host '    python scripts/check_llm.py' -ForegroundColor Gray
Write-Host '========================================' -ForegroundColor Cyan
