param([string]$UnityEditorPath)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Tools\Unity-Paths.ps1')
$editor = Resolve-ControlLabUnityEditor -UnityEditorPath $UnityEditorPath
$editorArguments = @(
    '-projectPath', ('"' + $PSScriptRoot + '"'),
    '-executeMethod', 'ControlLab.UnityPrototype.PrototypeBuilder.Prepare'
)
# This is an interactive editor window: the learner needs to see and control it.
Start-Process -FilePath $editor -ArgumentList $editorArguments -WorkingDirectory $PSScriptRoot
Write-Host 'The first-lesson scene will open after Unity imports the project.'
Write-Host 'Use the Play button in Unity to try the lesson. An activated editor license is required.'
