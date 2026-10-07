param([string]$Python = "")
$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($Python) {
            & $Python -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,14), 'Python 3.11-3.13 required'"
            if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version.' }
            & $Python -m venv (Join-Path $projectRoot '.venv')
        } else {
            & py -3.13 -m venv (Join-Path $projectRoot '.venv')
        }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. Supply -Python with a Python 3.11-3.13 executable.' }
    }
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip update failed.' }
    & $venvPython -m pip install -e '.[desktop,dev,packaging]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    Write-Host 'ControlLab is ready. Open this folder in VS Code, or run .\run.cmd to open the teaching application.'
} finally {
    Pop-Location
}
