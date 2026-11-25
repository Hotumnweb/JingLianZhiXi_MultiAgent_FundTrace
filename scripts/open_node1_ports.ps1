# 第一台电脑（Coordinator）端口放行脚本
# 用途：允许内网其他电脑访问第一台的平台 8501、Neo4j Browser 7474、Neo4j Bolt 7687。
# 用法（必须管理员）：
#   管理员 PowerShell 执行：
#     Set-ExecutionPolicy -Scope Process Bypass -Force
#     .\scripts\open_node1_ports.ps1
#   只允许指定来源（例如 Node2 192.168.0.200）：
#     .\scripts\open_node1_ports.ps1 -RemoteAddress 192.168.0.200
#
# 说明：Neo4j 还必须把 conf/neo4j.conf 的 server.default_listen_address 改成 0.0.0.0
# 并重启 Neo4j；本机已改好，其他机器/第三台 Node3 请参考
# docs/runbook_manual_operation.md 的 2.1 节。

param(
    [string]$RemoteAddress = 'LocalSubnet'
)

$ErrorActionPreference = 'Stop'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '[错误] 需要管理员权限：请右键“以管理员身份运行”，或用管理员 PowerShell 执行。' -ForegroundColor Red
    exit 1
}

$rules = @(
    @{ Name = 'JZ_Node1_Platform_8501'; Port = 8501; Note = 'Streamlit 平台' },
    @{ Name = 'JZ_Node1_Neo4j_Browser_7474'; Port = 7474; Note = 'Neo4j Browser' },
    @{ Name = 'JZ_Node1_Neo4j_Bolt_7687'; Port = 7687; Note = 'Neo4j Bolt' }
)

foreach ($rule in $rules) {
    Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP `
        -LocalPort $rule.Port -Action Allow -Profile Any -RemoteAddress $RemoteAddress | Out-Null
    Write-Host ("已放行 TCP {0}（{1}，来源 {2}）" -f $rule.Port, $rule.Note, $RemoteAddress) -ForegroundColor Green
}

Write-Host ''
Write-Host '完成。内网验证：' -ForegroundColor Cyan
Write-Host '  Streamlit 平台： http://192.168.0.199:8501'
Write-Host '  Neo4j Browser：  http://192.168.0.199:7474'
Write-Host '  Neo4j Bolt：     bolt://192.168.0.199:7687'
