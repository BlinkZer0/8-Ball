# ============================================================================
#  Runs the plugin UI (vst/ui) in headless Edge with a stand-in bridge
#  (tests/ui-tests.js) and reports the checks it makes. Also saves a
#  screenshot of the UI to vst/tests/screenshots/ui.png.
#  Usage: powershell -ExecutionPolicy Bypass -File run-ui-tests.ps1 [-Page ops|matrix|filters|art|fx|presets]
# ============================================================================
param([string]$Page = 'ops')
$ErrorActionPreference = 'Stop'
$vst = Split-Path $PSScriptRoot -Parent
$ui = Join-Path $vst 'ui'
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw 'Microsoft Edge not found' }

$utf8 = [Text.UTF8Encoding]::new($false)
$read = { param($p) [IO.File]::ReadAllText($p, $utf8) }
$html = & $read (Join-Path $ui 'index.html')
$html = $html.Replace('<link rel="stylesheet" href="css/style.css">', "<style>`n" + (& $read (Join-Path $ui 'css\style.css')) + "`n</style>")
# the mock bridge goes in before the UI's own scripts (after params.js, which it uses)
$html = [regex]::Replace($html, '<script src="js/([\w.-]+)"></script>', {
    param($m)
    $name = $m.Groups[1].Value
    $code = "<script>`n" + (& $read (Join-Path $ui "js\$name")) + "`n</script>"
    if ($name -eq 'params.js') { return "$code`n<script>`n" + (& $read (Join-Path $PSScriptRoot 'ui-tests.js')) + "`n</script>" }
    return $code
})
$html = $html.Replace('<footer class="statusbar">', "<script>window.__uiTestPage = '$Page';</script><pre id=`"ui-test-out`" style=`"display:none`"></pre><footer class=`"statusbar`">")
$html = $html.Replace("store.get('eightball.page') || 'ops'", "'$Page'")

$tmp = Join-Path $env:TEMP 'eightball-ui-tests'
New-Item -ItemType Directory -Force $tmp | Out-Null
$pagePath = Join-Path $tmp 'ui.html'
[IO.File]::WriteAllText($pagePath, $html, $utf8)
$shots = Join-Path $PSScriptRoot 'screenshots'
New-Item -ItemType Directory -Force $shots | Out-Null
$shot = Join-Path $shots "ui-$Page.png"

$domFile = Join-Path $tmp 'dom.txt'
$url = 'file:///' + ($pagePath -replace '\\', '/')
# two runs: Edge doesn't dump the DOM when it also takes a screenshot
Start-Process -FilePath $edge -Wait -RedirectStandardOutput $domFile -RedirectStandardError (Join-Path $tmp 'err.txt') -ArgumentList @(
    '--headless=new', '--disable-gpu', "--user-data-dir=$tmp\profile", '--window-size=1300,1080', '--hide-scrollbars',
    '--virtual-time-budget=5000', '--dump-dom', $url)
Start-Process -FilePath $edge -Wait -RedirectStandardOutput (Join-Path $tmp 'shot.txt') -RedirectStandardError (Join-Path $tmp 'err2.txt') -ArgumentList @(
    '--headless=new', '--disable-gpu', "--user-data-dir=$tmp\profile", '--window-size=1300,1080', '--hide-scrollbars',
    '--virtual-time-budget=5000', "--screenshot=$tmp\shot.png", $url)   # no spaces in this path: Edge would split it
if (Test-Path "$tmp\shot.png") { Move-Item -Force "$tmp\shot.png" $shot }
$dom = [IO.File]::ReadAllText($domFile)
if ($dom -match '(?s)<title>ERROR(.*?)</title>') { throw "UI test error: $([Net.WebUtility]::HtmlDecode($Matches[1]))" }
if ($dom -notmatch '(?s)<pre id="ui-test-out" style="display:none">(.*?)</pre>') {
    $t = if ($dom -match '(?s)<title>(.*?)</title>') { $Matches[1] } else { '(no title)' }
    throw "UI tests produced no output (page did not finish; title '$t', dom $($dom.Length) chars)"
}
$res = [Net.WebUtility]::HtmlDecode($Matches[1]) | ConvertFrom-Json
foreach ($r in $res.results) { Write-Host ("{0,-4} {1}" -f $(if ($r.ok) { 'ok' } else { 'FAIL' }), $r.what) }
Write-Host "screenshot: $shot"
if ($res.fails -eq 0) { Write-Host "UI TESTS OK ($($res.results.Count) checks)"; exit 0 }
Write-Host "UI TESTS: $($res.fails) FAILURE(S)"; exit 1
