[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$JavaHome = 'C:\Users\TICO\java\17.0.13+11'
$AndroidHome = 'C:\Users\TICO\Android\sdk'
$FlutterHome = 'C:\Users\TICO\flutter\3.29.2'
$SdkManager = Join-Path $AndroidHome 'cmdline-tools\12.0\bin\sdkmanager.bat'

foreach ($path in @($JavaHome, $AndroidHome, $FlutterHome, $SdkManager)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required tool/path not found: $path" }
}

$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidHome
$env:ANDROID_SDK_ROOT = $AndroidHome
$env:FLUTTER_HOME = $FlutterHome
$env:Path = (Join-Path $JavaHome 'bin') + ';' + (Join-Path $FlutterHome 'bin') + ';' + (Join-Path $AndroidHome 'cmdline-tools\12.0\bin') + ';' + (Join-Path $AndroidHome 'platform-tools') + ';' + $env:Path

Write-Host ''
Write-Host 'Android SDK license review' -ForegroundColor Cyan
Write-Host 'The next command displays Google license terms. Read them and accept only if you agree.' -ForegroundColor Yellow
Write-Host 'This script does not send automatic yes/no answers.' -ForegroundColor Yellow
Write-Host ''
& $SdkManager --licenses --sdk_root=$AndroidHome
if ($LASTEXITCODE -ne 0) { throw "sdkmanager --licenses failed with exit code $LASTEXITCODE" }

Write-Host ''
Write-Host 'Installing the minimum Android packages for Flutter 3.29.2 / compileSdk 35...' -ForegroundColor Cyan
& $SdkManager --install 'platform-tools' 'platforms;android-35' 'build-tools;35.0.0' --sdk_root=$AndroidHome
if ($LASTEXITCODE -ne 0) { throw "Android SDK package installation failed with exit code $LASTEXITCODE" }

$required = @(
    (Join-Path $AndroidHome 'platform-tools\adb.exe'),
    (Join-Path $AndroidHome 'platforms\android-35\android.jar'),
    (Join-Path $AndroidHome 'build-tools\35.0.0\aapt2.exe'),
    (Join-Path $AndroidHome 'build-tools\35.0.0\apksigner.bat')
)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) {
    Write-Host 'The SDK packages are not complete. Check that every required license was accepted.' -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "Missing: $_" -ForegroundColor Red }
    exit 2
}

Write-Host 'Android SDK core packages installed successfully.' -ForegroundColor Green
& (Join-Path $FlutterHome 'bin\flutter.bat') doctor -v