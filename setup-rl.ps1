param([string]$Python = "")
$ErrorActionPreference = 'Stop'
$runtimeRoot = $PSScriptRoot
# Installed copies keep optional Python and models in the user's Documents,
# outside application files that an update may replace.
$sourceCheckout = Test-Path -LiteralPath (Join-Path $runtimeRoot 'pyproject.toml')
$rlDirectory = if ($sourceCheckout) { Join-Path $runtimeRoot '.venv-rl' } else {
    Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'ControlLab\runtimes\rl'
}
$rlPython = Join-Path $rlDirectory 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $rlPython)) {
    if (-not $Python -and $sourceCheckout) {
        $candidate = Join-Path $runtimeRoot '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $candidate) { $Python = $candidate }
    }
    if ($Python) {
        & $Python -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,14), 'Use Python 3.11-3.13'"
        if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version.' }
        & $Python -m venv $rlDirectory
    } else { & py -3.13 -m venv $rlDirectory }
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11-3.13 or provide -Python with its executable path.' }
}
& $rlPython -m pip install 'torch==2.9.1+cpu' --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
& $rlPython -m pip install -r (Join-Path $runtimeRoot 'requirements-rl-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Training dependencies installation failed.' }
if ($sourceCheckout) {
    & $rlPython -m pip install --no-deps -e $runtimeRoot
} else {
    $runtimeWheel = Get-ChildItem -LiteralPath $runtimeRoot -Filter 'control_lab-*.whl' | Select-Object -First 1
    if (-not $runtimeWheel) { throw 'The teaching runtime wheel is missing; extract the complete release.' }
    & $rlPython -m pip install --no-deps --upgrade $runtimeWheel.FullName
}
if ($LASTEXITCODE -ne 0) { throw 'ControlLab runtime installation failed.' }
& $rlPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependencies do not match.' }
& $rlPython -c "import torch,stable_baselines3; from control_lab.rl.env_factory import make_training_env; e=make_training_env(); e.reset(seed=0); e.step([0.0]); e.close(); print('CPU training runtime ready')"
if ($LASTEXITCODE -ne 0) { throw 'Training environment verification failed.' }
Write-Host "Select this interpreter in ControlLab: $rlPython"
