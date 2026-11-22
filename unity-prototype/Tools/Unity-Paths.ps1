function Resolve-ControlLabUnityEditor {
    param([string]$UnityEditorPath)

    if ($UnityEditorPath) {
        if (-not (Test-Path -LiteralPath $UnityEditorPath -PathType Leaf)) {
            throw "Unity Editor was not found: $UnityEditorPath"
        }
        return (Resolve-Path -LiteralPath $UnityEditorPath).Path
    }

    $candidates = @(
        $env:UNITY_EDITOR_PATH,
        'E:\Software\Unity\6000.5.7f1\Editor\Unity.exe',
        (Join-Path $env:ProgramFiles 'Unity\Hub\Editor\6000.5.7f1\Editor\Unity.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'Unity 6000.5.7f1 was not found. Pass -UnityEditorPath or set UNITY_EDITOR_PATH.'
}
