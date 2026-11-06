[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$JavaHome = 'C:\Users\TICO\java\17.0.13+11'
$AndroidHome = 'C:\Users\TICO\Android\sdk'
$FlutterHome = 'C:\Users\TICO\flutter\3.29.2'
$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidHome
$env:ANDROID_SDK_ROOT = $AndroidHome
$env:FLUTTER_HOME = $FlutterHome
$env:Path = (Join-Path $JavaHome 'bin') + ';' + (Join-Path $FlutterHome 'bin') + ';' + (Join-Path $AndroidHome 'cmdline-tools\12.0\bin') + ';' + (Join-Path $AndroidHome 'platform-tools') + ';' + $env:Path

Write-Host '=== Tool versions ===' -ForegroundColor Cyan
& (Join-Path $JavaHome 'bin\java.exe') -version
& (Join-Path $FlutterHome 'bin\flutter.bat') --version --no-version-check --suppress-analytics
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $Python) { & $Python --version; & $Python -m pip show flet flet-permission-handler flet-webview }

Write-Host '=== Android SDK components ===' -ForegroundColor Cyan
$checks = @(
    'platform-tools\adb.exe',
    'platforms\android-35\android.jar',
    'build-tools\35.0.0\aapt2.exe',
    'build-tools\35.0.0\apksigner.bat'
)
foreach ($relative in $checks) {
    $full = Join-Path $AndroidHome $relative
    $state = if (Test-Path -LiteralPath $full) { 'OK' } else { 'MISSING' }
    Write-Host ("{0,-8} {1}" -f $state, $relative)
}

Write-Host '=== Flutter doctor ===' -ForegroundColor Cyan
& (Join-Path $FlutterHome 'bin\flutter.bat') doctor -v