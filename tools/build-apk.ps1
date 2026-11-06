[CmdletBinding()]
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$JavaHome = 'C:\Users\TICO\java\17.0.13+11'
$AndroidHome = 'C:\Users\TICO\Android\sdk'
$FlutterHome = 'C:\Users\TICO\flutter\3.29.2'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Flet = Join-Path $ProjectRoot '.venv\Scripts\flet.exe'

foreach ($path in @($JavaHome, $AndroidHome, $FlutterHome, $Python, $Flet)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required tool/path not found: $path" }
}
$requiredSdk = @(
    (Join-Path $AndroidHome 'platform-tools\adb.exe'),
    (Join-Path $AndroidHome 'platforms\android-35\android.jar'),
    (Join-Path $AndroidHome 'build-tools\35.0.0\aapt2.exe'),
    (Join-Path $AndroidHome 'build-tools\35.0.0\apksigner.bat')
)
$missing = @($requiredSdk | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) {
    Write-Host 'Android SDK is not ready. Run .\tools\install-android-sdk.ps1 and review/accept its licenses first.' -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "Missing: $_" -ForegroundColor Red }
    exit 2
}

$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidHome
$env:ANDROID_SDK_ROOT = $AndroidHome
$env:FLUTTER_HOME = $FlutterHome
$env:PYTHONIOENCODING = 'utf-8'
$env:FLET_CLI_NO_RICH_OUTPUT = '1'
$env:Path = (Join-Path $JavaHome 'bin') + ';' + (Join-Path $FlutterHome 'bin') + ';' + (Join-Path $AndroidHome 'platform-tools') + ';' + (Join-Path $AndroidHome 'cmdline-tools\12.0\bin') + ';' + $env:Path

Push-Location $ProjectRoot
try {
    if (-not $SkipTests) {
        & $Python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw "Python tests failed with exit code $LASTEXITCODE" }
    }
    & $Python -m py_compile main.py payload_sender.py ps5_ftp.py ps5_media.py jxr_preview.py jxr_thumbnails.py
    if ($LASTEXITCODE -ne 0) { throw "Python syntax check failed with exit code $LASTEXITCODE" }

    & $Flet build apk --verbose --output build\apk
    if ($LASTEXITCODE -ne 0) { throw "Flet APK build failed with exit code $LASTEXITCODE" }

    $apk = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'build\apk') -Filter '*.apk' -File -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $apk) { throw 'Build returned success but no APK was found under build\apk.' }
    Write-Host "APK ready: $($apk.FullName)" -ForegroundColor Green
    Write-Host "Size: $([math]::Round($apk.Length / 1MB, 2)) MB"
}
finally { Pop-Location }