# ============================================================================
#  Checks that vst/ui/js/params.js matches vst/Source/dsp/ParamTable.h exactly:
#  same order, IDs, names, types, ranges, defaults, steps, units, log skew,
#  choice lists and "not in presets" flags. The C++ table comes from
#  EightBallTests --dump-params; the JS table is evaluated in headless Edge.
#  Usage: powershell -ExecutionPolicy Bypass -File check-params.ps1
# ============================================================================
$ErrorActionPreference = 'Stop'
$vst = Split-Path $PSScriptRoot -Parent
$exe = Join-Path $env:LOCALAPPDATA 'EightBallVST\build\EightBallTests_artefacts\Release\EightBallTests.exe'
if (-not (Test-Path $exe)) { throw "Build EightBallTests first: $exe" }
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw 'Microsoft Edge not found (needed to evaluate params.js headless)' }

$cpp = (& $exe --dump-params | Out-String) | ConvertFrom-Json

$tmp = Join-Path $env:TEMP 'eightball-check-params'
New-Item -ItemType Directory -Force $tmp | Out-Null
$page = @'
<!doctype html><html><head><title>running</title></head><body><pre id="out"></pre>
<script>PARAMS_JS</script>
<script>
try {
  const out = PARAM_DEFS.map(d => ({ id: d.id, name: d.name, type: d.type, min: d.min, max: d.max, def: d.def, step: d.step || 0,
    unit: d.unit || '', log: d.skew === 'log', noPreset: !!d.noPreset, choices: d.choices || [] }));
  document.getElementById('out').textContent = JSON.stringify(out);
  document.title = 'done';
} catch (e) { document.title = 'ERROR ' + (e.stack || e); }
</script></body></html>
'@
$page = $page.Replace('PARAMS_JS', [IO.File]::ReadAllText((Join-Path $vst 'ui\js\params.js')))
$pagePath = Join-Path $tmp 'params.html'
[IO.File]::WriteAllText($pagePath, $page, [Text.UTF8Encoding]::new($false))
$domFile = Join-Path $tmp 'dom.txt'
Start-Process -FilePath $edge -Wait -RedirectStandardOutput $domFile -RedirectStandardError (Join-Path $tmp 'err.txt') -ArgumentList @(
    '--headless=new', '--disable-gpu', "--user-data-dir=$tmp\profile", '--dump-dom', ('file:///' + ($pagePath -replace '\\', '/')))
$dom = [IO.File]::ReadAllText($domFile)
if ($dom -match '(?s)<title>ERROR(.*?)</title>') { throw "params.js error: $([Net.WebUtility]::HtmlDecode($Matches[1]))" }
if ($dom -notmatch '(?s)<pre id="out">(.*?)</pre>') { throw 'params.js produced no output' }
$js = [Net.WebUtility]::HtmlDecode($Matches[1]) | ConvertFrom-Json

$fail = 0
if ($cpp.Count -ne $js.Count) { Write-Host "COUNT differs: C++ $($cpp.Count), JS $($js.Count)"; $fail++ }
$n = [Math]::Min($cpp.Count, $js.Count)
for ($i = 0; $i -lt $n; $i++) {
    $c = $cpp[$i]; $j = $js[$i]
    $diffs = @()
    foreach ($f in 'id', 'name', 'type', 'unit') { if ([string]$c.$f -ne [string]$j.$f) { $diffs += "$f C++ '$($c.$f)' JS '$($j.$f)'" } }
    foreach ($f in 'min', 'max', 'def', 'step') { if ([Math]::Abs([double]$c.$f - [double]$j.$f) -gt 1e-5) { $diffs += "$f C++ $($c.$f) JS $($j.$f)" } }
    foreach ($f in 'log', 'noPreset') { if ([bool]$c.$f -ne [bool]$j.$f) { $diffs += "$f C++ $($c.$f) JS $($j.$f)" } }
    $cc = @($c.choices); $jc = @($j.choices)
    if (($cc -join '|') -ne ($jc -join '|')) { $diffs += "choices differ ($($cc.Count) vs $($jc.Count))" }
    if ($diffs.Count) { $fail++; Write-Host ("#{0} {1}: {2}" -f $i, $c.id, ($diffs -join '; ')) }
}
if ($fail -eq 0) { Write-Host "PARAMS OK ($n parameters match)"; exit 0 }
Write-Host "PARAMS: $fail difference(s)"; exit 1
