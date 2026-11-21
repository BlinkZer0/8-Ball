# ============================================================================
#  Runs the WEB BUILD (web/index.html) in headless Edge with tests/web-tests.js
#  appended: the real bridge (webhost/web-host.js) and the engine as
#  WebAssembly under the UI. Builds the page first with -Build.
#  Usage: powershell -ExecutionPolicy Bypass -File run-web-tests.ps1 [-Build]
# ============================================================================
param([switch]$Build)
$ErrorActionPreference = 'Stop'
$vst = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $vst -Parent
$page = Join-Path $repo 'web\index.html'
if ($Build -or -not (Test-Path $page)) { & (Join-Path $vst 'webhost\build-web.ps1') }
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw 'Microsoft Edge not found' }

$utf8 = [Text.UTF8Encoding]::new($false)
$html = [IO.File]::ReadAllText($page, $utf8)
$test = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'web-tests.js'), $utf8)
if ($test -match '</script') { throw 'web-tests.js must not contain </script' }
$html = $html.Replace('</body>', "<script>`n$test`n</script>`n</body>")

$tmp = Join-Path $env:TEMP 'eightball-web-tests'
New-Item -ItemType Directory -Force $tmp | Out-Null
$pagePath = Join-Path $tmp 'web.html'
[IO.File]::WriteAllText($pagePath, $html, $utf8)
$shots = Join-Path $PSScriptRoot 'screenshots'
New-Item -ItemType Directory -Force $shots | Out-Null
$domFile = Join-Path $tmp 'dom.txt'
$url = 'file:///' + ($pagePath -replace '\\', '/')
$args = @('--headless=new', '--disable-gpu', "--user-data-dir=$tmp\profile", '--window-size=1300,1080', '--hide-scrollbars',
          '--autoplay-policy=no-user-gesture-required', '--virtual-time-budget=15000')
Start-Process -FilePath $edge -Wait -RedirectStandardOutput $domFile -RedirectStandardError (Join-Path $tmp 'err.txt') -ArgumentList ($args + @('--dump-dom', $url))
Start-Process -FilePath $edge -Wait -RedirectStandardOutput (Join-Path $tmp 'shot.txt') -RedirectStandardError (Join-Path $tmp 'err2.txt') -ArgumentList ($args + @("--screenshot=$tmp\shot.png", $url))
if (Test-Path "$tmp\shot.png") { Move-Item -Force "$tmp\shot.png" (Join-Path $shots 'web.png') }
$dom = [IO.File]::ReadAllText($domFile)
if ($dom -notmatch '(?s)<pre id="web-test-out" style="display: ?none;?">(.*?)</pre>') {
    $t = if ($dom -match '(?s)<title>(.*?)</title>') { $Matches[1] } else { '(no title)' }
    throw "Web tests produced no output (page did not finish; title '$t', dom $($dom.Length) chars)"
}
$res = [Net.WebUtility]::HtmlDecode($Matches[1]) | ConvertFrom-Json
foreach ($r in $res.results) { Write-Host ("{0,-4} {1}" -f $(if ($r.ok) { 'ok' } else { 'FAIL' }), $r.what) }
Write-Host "screenshot: $(Join-Path $shots 'web.png')"
if ($res.fails -eq 0) { Write-Host "WEB TESTS OK ($($res.results.Count) checks)"; exit 0 }
Write-Host "WEB TESTS: $($res.fails) FAILURE(S)"; exit 1
