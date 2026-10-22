param([switch]$LaunchEasyConnect)
$ErrorActionPreference = 'Stop'
$processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^EasyConnect$|^SangforCSClient$' })
$candidates = @()
foreach ($baseDir in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
    if ($baseDir) {
        $candidates += Join-Path $baseDir 'Sangfor\SSL\EasyConnect\EasyConnect.exe'
        $candidates += Join-Path $baseDir 'Sangfor\EasyConnect\EasyConnect.exe'
        $candidates += Join-Path $baseDir 'EasyConnect\EasyConnect.exe'
        $candidates += Join-Path $baseDir 'Sangfor\SSL\SangforCSClient\SangforCSClient.exe'
    }
}
foreach ($process in $processes) {
    try { if ($process.Path) { $candidates += $process.Path } } catch { }
}
$installed = @($candidates | Select-Object -Unique | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
$launched = $false
if ($LaunchEasyConnect -and $processes.Count -eq 0 -and $installed.Count -gt 0) {
    # Interactive login is the requested purpose of this explicit switch.
    Start-Process -FilePath $installed[0] -WindowStyle Normal
    $launched = $true
}
[ordered]@{
    easyconnect_process_seen = ($processes.Count -gt 0)
    executable_candidates = $installed
    launched_for_manual_login = $launched
    authentication = 'unknown'
    next_check = 'Inspect EasyConnect connection state, campus CNKI page, and institution authentication in local Chrome.'
    vpn_url = 'https://vpn.htu.edu.cn'
    cnki_url = 'http://www-cnki-net-s.vpn.htu.edu.cn:8118'
    help_url = 'https://www.htu.edu.cn/info/2011/0116/c18431a250850/page.htm'
} | ConvertTo-Json -Depth 3
