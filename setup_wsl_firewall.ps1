$ErrorActionPreference = "Stop"

$ruleName = "Pepper-NAOqi-Callbacks"
$creatorId = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"
$existing = Get-NetFirewallHyperVRule -Name $ruleName -ErrorAction SilentlyContinue

if ($null -eq $existing) {
    New-NetFirewallHyperVRule `
        -Name $ruleName `
        -DisplayName "Pepper NAOqi callbacks" `
        -Direction Inbound `
        -VMCreatorId $creatorId `
        -Protocol TCP `
        -LocalPorts 54000, 54001, 54002 `
        -RemoteAddresses 192.168.0.100 `
        -Action Allow `
        -Enabled True
}

Get-NetFirewallHyperVRule -Name $ruleName | Format-List `
    Name, DisplayName, Enabled, Direction, Protocol, LocalPorts, RemoteAddresses, Action, VMCreatorId
