[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FlutterHome = 'C:\Users\TICO\flutter\3.29.2'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Flet = Join-Path $ProjectRoot '.venv\Scripts\flet.exe'
if (-not (Test-Path -LiteralPath $Flet)) { throw "Flet CLI not found: $Flet" }
$env:FLUTTER_HOME = $FlutterHome
$env:PYTHONIOENCODING = 'utf-8'
$env:FLET_CLI_NO_RICH_OUTPUT = '1'
$env:Path = (Join-Path $FlutterHome 'bin') + ';' + $env:Path
Push-Location $ProjectRoot
try {
    & $Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Python tests failed.' }
    & $Flet build windows --verbose --output build\windows
    if ($LASTEXITCODE -ne 0) { throw "Flet Windows build failed with exit code $LASTEXITCODE" }
    Write-Host "Windows build output: $(Join-Path $ProjectRoot 'build\windows')" -ForegroundColor Green
}
finally { Pop-Location }