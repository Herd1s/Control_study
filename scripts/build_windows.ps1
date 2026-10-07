param([switch]$Installer, [string]$Iscc = "")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run setup.ps1 first.' }
    $appVersion = (& $venvPython -c 'from control_lab import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read application version.' }
    & $venvPython -m PyInstaller --noconfirm packaging/windows/ControlLab.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    & $venvPython scripts/collect_notices.py dist/ControlLab/THIRD_PARTY_NOTICES.txt
    if ($LASTEXITCODE -ne 0) { throw 'Collecting dependency notices failed.' }
    Copy-Item -LiteralPath 'packaging/windows/Start-Demo.cmd' -Destination 'dist/ControlLab/Start-Demo.cmd'
    Copy-Item -LiteralPath 'packaging/windows/QUICKSTART.txt' -Destination 'dist/ControlLab/QUICKSTART.txt'
    & $venvPython -m build --wheel --outdir build/runtime-wheel
    if ($LASTEXITCODE -ne 0) { throw 'Optional training runtime wheel build failed.' }
    $runtimeBundle = Join-Path $projectRoot 'dist\ControlLab\runtime'
    New-Item -ItemType Directory -Path $runtimeBundle -Force | Out-Null
    $wheelFile = Join-Path $projectRoot ('build\runtime-wheel\control_lab-' + $appVersion + '-py3-none-any.whl')
    Copy-Item -LiteralPath $wheelFile -Destination $runtimeBundle
    Copy-Item -LiteralPath 'setup-rl.ps1','requirements-rl-lock.txt' -Destination $runtimeBundle
    $runtimeManifest = [ordered]@{
        schema_version = 1
        app_version = $appVersion
        wheel_filename = Split-Path -Leaf $wheelFile
        wheel_sha256 = (Get-FileHash -LiteralPath $wheelFile -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $runtimeManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeBundle 'runtime-manifest.json') -Encoding utf8
    & (Join-Path $runtimeBundle 'setup-rl.ps1') -ValidateOnly
    if (-not $?) { throw 'Packaged runtime manifest verification failed.' }
    Write-Host 'Portable application: dist\ControlLab (distribute the whole folder).'
    if ($Installer) {
        if (-not $Iscc) {
            $compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
            if ($compiler) { $Iscc = $compiler.Source }
            else {
                $userCompiler = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
                if (Test-Path -LiteralPath $userCompiler) { $Iscc = $userCompiler }
            }
        }
        if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc)) { throw 'Inno Setup compiler not found. The portable build is ready; pass -Iscc with the ISCC.exe path to also build Setup.' }
        & $Iscc ('/DMyAppVersion=' + $appVersion) 'packaging/windows/installer.iss'
        if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    }
} finally {
    Pop-Location
}
