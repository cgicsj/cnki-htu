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
$skillRoots = @((Join-Path $env:USERPROFILE '.agents\skills'), (Join-Path $env:USERPROFILE '.codex\skills'), (Join-Path (Get-Location) '.agents\skills'))
if ($env:CODEX_HOME) { $skillRoots += Join-Path $env:CODEX_HOME 'skills' }
$egoSkills = @($skillRoots | Select-Object -Unique | ForEach-Object { Join-Path $_ 'ego-browser\SKILL.md' } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
$egoCommand = Get-Command ego-browser -ErrorAction SilentlyContinue
if ($LaunchEasyConnect -and $processes.Count -eq 0 -and $installed.Count -gt 0) {
    # Interactive login is the requested purpose of this explicit switch.
    Start-Process -FilePath $installed[0] -WindowStyle Normal
    $launched = $true
}
[ordered]@{
    ego_browser_skill_candidates = $egoSkills
    ego_browser_cli_available = [bool]$egoCommand
    browser_preference = 'Read the agent skill catalog first; prefer installed ego-browser after following its SKILL.md. Files/CLI alone do not prove connectivity or authentication.'
    easyconnect_process_seen = ($processes.Count -gt 0)
    executable_candidates = $installed
    launched_for_manual_login = $launched
    authentication = 'unknown'
    next_check = 'Select ego-browser when installed, otherwise local Chrome; inspect EasyConnect, campus CNKI page, and institution authentication in that browser.'
    vpn_url = 'https://vpn.htu.edu.cn'
    cnki_url = 'http://www-cnki-net-s.vpn.htu.edu.cn:8118'
    help_url = 'https://www.htu.edu.cn/info/2011/0116/c18431a250850/page.htm'
} | ConvertTo-Json -Depth 3
