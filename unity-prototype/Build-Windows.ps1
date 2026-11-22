param([string]$UnityEditorPath)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Tools\Unity-Paths.ps1')
$editor = Resolve-ControlLabUnityEditor -UnityEditorPath $UnityEditorPath
$logDirectory = Join-Path $PSScriptRoot 'Logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory ('build-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$editorArguments = @(
    '-batchmode', '-nographics', '-quit',
    '-projectPath', ('"' + $PSScriptRoot + '"'),
    '-buildTarget', 'Win64',
    '-executeMethod', 'ControlLab.UnityPrototype.PrototypeBuilder.Build',
    '-logFile', ('"' + $logPath + '"')
)
Write-Host 'Building the Windows prototype. Close this project in Unity before continuing.'
$buildProcess = Start-Process -FilePath $editor -ArgumentList $editorArguments `
    -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -Wait
$logText = if (Test-Path -LiteralPath $logPath) { Get-Content -LiteralPath $logPath -Raw } else { '' }
if ($logText -match 'No valid Unity Editor license found') {
    throw "Activate your applicable license in Unity Hub, then run this script again. Log: $logPath"
}
$executable = Join-Path $PSScriptRoot 'Builds\Windows\ControlLab Unity.exe'
if ($buildProcess.ExitCode -ne 0 -or $logText -notmatch 'CONTROLLAB_BUILD_OK' -or -not (Test-Path -LiteralPath $executable)) {
    throw "Unity build did not complete (exit $($buildProcess.ExitCode)). Log: $logPath"
}
Write-Host "Built: $executable"
Write-Host 'Share the complete Builds\Windows folder, including the _Data folder and DLLs.'
