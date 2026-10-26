# 第一台电脑（Coordinator）端口放行脚本
# 用途：允许第二台电脑访问第一台平台 8501 与 Neo4j 7687（仅局域网）。
# 用法：右键“使用 PowerShell 运行”（需管理员），或管理员 PowerShell 执行：
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\scripts\open_node1_ports.ps1
#
# 说明：如果第三台/第二台需要访问本机 Neo4j，还需把 neo4j.conf 的
# server.default_listen_address 从 127.0.0.1 改为 0.0.0.0 并重启 Neo4j。

$ErrorActionPreference = 'Stop'

$rules = @(
    @{ Name = 'JZ_Node1_Platform_8501'; Port = 8501 },
    @{ Name = 'JZ_Node1_Neo4j_7687'; Port = 7687 }
)

foreach ($rule in $rules) {
    $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Remove-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
    }
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP `
        -LocalPort $rule.Port -Action Allow -Profile Any -RemoteAddress LocalSubnet | Out-Null
    Write-Host ("已放行 TCP " + $rule.Port + "（仅本地子网）") -ForegroundColor Green
}

Write-Host ''
Write-Host '完成。第二台可用浏览器访问 http://192.168.0.199:8501 验证平台。' -ForegroundColor Cyan
