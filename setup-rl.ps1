param([string]$Python = "", [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$runtimeRoot = $PSScriptRoot
# Installed copies keep optional Python and models in the user's Documents,
# outside application files that an update may replace.
$sourceCheckout = Test-Path -LiteralPath (Join-Path $runtimeRoot 'pyproject.toml')
$runtimeWheel = $null
if (-not $sourceCheckout) {
    # Upgrade installs can retain older wheel files. Select only the exact wheel
    # named by this release's manifest; directory enumeration is not a version policy.
    $manifestPath = Join-Path $runtimeRoot 'runtime-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw 'runtime-manifest.json is missing. Extract the complete release or reinstall the application; do not run a loose setup-rl.ps1 file.'
    }
    try { $runtimeManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json }
    catch { throw 'runtime-manifest.json is unreadable. Extract the complete release again.' }
    if ($runtimeManifest.schema_version -ne 1 -or $runtimeManifest.app_version -notmatch '\A\d+\.\d+\.\d+\z' -or
        $runtimeManifest.wheel_sha256 -notmatch '\A[a-fA-F0-9]{64}\z') {
        throw 'runtime-manifest.json has an unsupported schema, version, or SHA256.'
    }
    $expectedWheelName = 'control_lab-' + $runtimeManifest.app_version + '-py3-none-any.whl'
    if ($runtimeManifest.wheel_filename -cne $expectedWheelName) {
        throw 'The wheel filename does not match the runtime manifest version.'
    }
    $runtimeWheel = Join-Path $runtimeRoot $expectedWheelName
    if (-not (Test-Path -LiteralPath $runtimeWheel -PathType Leaf)) {
        throw "The runtime wheel for application $($runtimeManifest.app_version) is missing: $expectedWheelName"
    }
    $hashAlgorithm = [System.Security.Cryptography.SHA256]::Create()
    $wheelStream = [System.IO.File]::OpenRead($runtimeWheel)
    try {
        $actualDigest = [System.BitConverter]::ToString($hashAlgorithm.ComputeHash($wheelStream)).Replace('-', '').ToLowerInvariant()
    } finally {
        $wheelStream.Dispose()
        $hashAlgorithm.Dispose()
    }
    if ($actualDigest -ne $runtimeManifest.wheel_sha256.ToLowerInvariant()) {
        throw 'Runtime wheel SHA256 mismatch. No environment changes were made; obtain the complete release again.'
    }
    if ($ValidateOnly) {
        [pscustomobject]@{ schema_version = 1; app_version = $runtimeManifest.app_version; wheel = $runtimeWheel; sha256 = $actualDigest } | ConvertTo-Json -Compress
        return
    }
} elseif ($ValidateOnly) {
    [pscustomobject]@{ source_checkout = $true; path = $runtimeRoot } | ConvertTo-Json -Compress
    return
}
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
    & $rlPython -m pip install --no-deps --upgrade $runtimeWheel
}
if ($LASTEXITCODE -ne 0) { throw 'ControlLab runtime installation failed.' }
& $rlPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependencies do not match.' }
& $rlPython -c "import torch,stable_baselines3; from control_lab.rl.tasks import TaskStore; from control_lab.rl.catalog import ModelCatalog; from control_lab.rl import task_runner; from control_lab.rl.env_factory import make_training_env; e=make_training_env(); e.reset(seed=0); e.step([0.0]); e.close(); print('CPU training runtime ready')"
if ($LASTEXITCODE -ne 0) { throw 'Training environment verification failed.' }
Write-Host "Select this interpreter in ControlLab: $rlPython"
