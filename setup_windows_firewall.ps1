param(
    [string]$RobotIp = $(if ($env:PEPPER_ROBOT_IP) { $env:PEPPER_ROBOT_IP } else { "192.168.0.100" })
)

$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an Administrator PowerShell window. It opens TCP 54000, 54001, and 54002 for Pepper."
}

if ([string]::IsNullOrWhiteSpace($RobotIp)) {
    throw "Pepper IP is empty. Example: .\setup_windows_firewall.ps1 -RobotIp 192.168.0.100"
}

$ruleName = "Pepper-NAOqi-Callbacks-Windows"
$existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -Name $ruleName
}

New-NetFirewallRule `
    -Name $ruleName `
    -DisplayName "Pepper NAOqi callbacks" `
    -Direction Inbound `
    -Action Allow `
    -Enabled True `
    -Profile Domain,Private,Public `
    -Protocol TCP `
    -LocalPort 54000,54001,54002 `
    -RemoteAddress $RobotIp

Write-Host "Pepper $RobotIp is allowed to access Windows TCP 54000, 54001, and 54002."
