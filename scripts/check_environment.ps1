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
    browser_preference = 'Prefer chrome-mcp to operate the local Chrome session; read the current tool documentation before use.'
    chrome_mcp_availability = 'unknown; inspect the current agent tool catalog and verify the actual Chrome connection'
    easyconnect_process_seen = ($processes.Count -gt 0)
    executable_candidates = $installed
    launched_for_manual_login = $launched
    authentication = 'unknown'
    next_check = 'Connect to local Chrome with chrome-mcp; inspect EasyConnect, campus CNKI page, and institution authentication in that session.'
    vpn_url = 'https://vpn.htu.edu.cn'
    cnki_url = 'http://www-cnki-net-s.vpn.htu.edu.cn:8118'
    help_url = 'https://www.htu.edu.cn/info/2011/0116/c18431a250850/page.htm'
} | ConvertTo-Json -Depth 3
