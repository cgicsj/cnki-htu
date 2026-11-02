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
    browser_preference = 'Prefer the Codex Chrome plugin (@Chrome) to operate the local Chrome session; fall back to Chrome DevTools MCP only when the plugin is unavailable; read the current tool documentation before use.'
    browser_tool_availability = 'unknown; inspect the current agent tool catalog and verify the actual Chrome connection'
    insecure_content = [ordered]@{
        status = 'unknown'
        required_stage = 'environment_check_before_search_and_download'
        settings_url = 'chrome://settings/content/insecureContent'
        allowed_pattern = '[*.]htu.edu.cn'
        verification = 'Inspect the actual Chrome allow list or record explicit user confirmation; this script does not read or change browser permissions.'
    }
    easyconnect_process_seen = ($processes.Count -gt 0)
    executable_candidates = $installed
    launched_for_manual_login = $launched
    authentication = 'unknown'
    next_check = 'Connect to local Chrome with the Codex Chrome plugin (@Chrome), or Chrome DevTools MCP when the plugin is unavailable; complete the insecure-content allow-list check for [*.]htu.edu.cn during environment setup, then verify EasyConnect, campus access and institution authentication before search or download.'
    vpn_url = 'https://vpn.htu.edu.cn'
    cnki_url = 'http://www-cnki-net-s.vpn.htu.edu.cn:8118'
    help_url = 'https://www.htu.edu.cn/info/2011/0116/c18431a250850/page.htm'
} | ConvertTo-Json -Depth 3
