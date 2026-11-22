<#
.SYNOPSIS
Type-check the prototype with the installed Unity compiler and reference assemblies.
.DESCRIPTION
Does not launch Unity, import assets, run the scene, or build a Player. The generated
DLLs are temporary compiler outputs for source verification only. A licensed Unity
Editor is still required for scene validation and a distributable Windows build.
.PARAMETER UnityEditorPath
Optional full path to Unity.exe. Otherwise use the shared Unity path discovery.
#>
[CmdletBinding()]
param([string]$UnityEditorPath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Unity-Paths.ps1')

$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $projectRoot 'Logs\Verification\source-check'
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$reportPath = Join-Path $outputRoot 'result.json'
$report = [ordered]@{
    check = 'source-type-check'
    playerBuild = $false
    assetImportChecked = $false
    sceneExecutionChecked = $false
    startedUtc = [DateTime]::UtcNow.ToString('o')
    success = $false
    stages = @()
}

function Find-ReferenceAssemblies {
    param([string[]]$Directories, [string]$Filter)
    # Unity versions place their facade/module DLLs in slightly different folders.
    # Prefer the first occurrence to avoid referencing two copies of an assembly.
    $byName = @{}
    foreach ($directory in $Directories) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $directory -Filter $Filter -File) {
            if (-not $byName.ContainsKey($file.Name)) { $byName[$file.Name] = $file.FullName }
        }
    }
    @($byName.Values | Sort-Object)
}

function Invoke-SourceCheck {
    param(
        [string]$Name,
        [string[]]$Sources,
        [string[]]$References,
        [string[]]$Symbols
    )
    if ($Sources.Count -eq 0) { throw "No source files found for $Name." }
    $assemblyPath = Join-Path $outputRoot ($Name + '.dll')
    $responsePath = Join-Path $outputRoot ($Name + '.rsp')
    $logPath = Join-Path $outputRoot ($Name + '.log')
    # Remove only the previous compiler artifact, never an application or project file.
    if (Test-Path -LiteralPath $assemblyPath) { Remove-Item -LiteralPath $assemblyPath }
    $sourceHashes = @($Sources | ForEach-Object {
        [ordered]@{
            path = $_.Substring($projectRoot.Length + 1).Replace('\', '/')
            sha256 = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash
        }
    })
    $arguments = @(
        '-nologo', '-nostdlib+', '-target:library', '-langversion:9.0',
        '-deterministic+', '-optimize+', '-warn:4', '-utf8output',
        ('-define:' + ($Symbols -join ';')),
        ('-out:"' + $assemblyPath + '"')
    )
    $arguments += @($References | ForEach-Object { '-reference:"' + $_ + '"' })
    $arguments += @($Sources | ForEach-Object { '"' + $_ + '"' })
    [IO.File]::WriteAllLines($responsePath, $arguments, [Text.UTF8Encoding]::new($false))

    Write-Host "Checking $Name ($($Sources.Count) source files)..."
    # This executes the bundled .NET compiler host, not Unity.exe.
    $compilerOutput = @(& $dotnetPath $compilerPath '-noconfig' ('@' + $responsePath) 2>&1)
    $compilerExitCode = $LASTEXITCODE
    $compilerText = ($compilerOutput | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    [IO.File]::WriteAllText($logPath, $compilerText, [Text.UTF8Encoding]::new($false))
    if ($compilerText) { Write-Host $compilerText }

    $sourcesUnchanged = $true
    for ($i = 0; $i -lt $Sources.Count; $i++) {
        if ((Get-FileHash -LiteralPath $Sources[$i] -Algorithm SHA256).Hash -ne $sourceHashes[$i].sha256) {
            $sourcesUnchanged = $false
        }
    }
    $stage = [ordered]@{
        name = $Name
        exitCode = $compilerExitCode
        success = ($compilerExitCode -eq 0 -and $sourcesUnchanged -and (Test-Path -LiteralPath $assemblyPath))
        sourcesUnchanged = $sourcesUnchanged
        sources = $sourceHashes
        referenceCount = $References.Count
        log = $logPath
        assembly = $assemblyPath
    }
    $report.stages += $stage
    if (-not $stage.success) {
        if (-not $sourcesUnchanged) { throw "$Name changed while checking. Run this check again after edits finish." }
        throw "$Name source check failed (compiler exit $compilerExitCode). See $logPath"
    }
    return $assemblyPath
}

try {
    $editorPath = Resolve-ControlLabUnityEditor -UnityEditorPath $UnityEditorPath
    $dataRoot = Join-Path (Split-Path -Parent $editorPath) 'Data'
    $sdkRoot = Join-Path $dataRoot 'DotNetSdk'
    $dotnetPath = Join-Path $sdkRoot 'dotnet.exe'
    $compilerPath = Get-ChildItem -LiteralPath (Join-Path $sdkRoot 'sdk') -Directory |
        Sort-Object { [version]($_.Name -replace '-.*$', '') } -Descending |
        ForEach-Object { Join-Path $_.FullName 'Roslyn\bincore\csc.dll' } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
    if (-not (Test-Path -LiteralPath $dotnetPath -PathType Leaf) -or -not $compilerPath) {
        throw 'This Unity installation does not contain the expected DotNetSdk/Roslyn compiler.'
    }
    $managedRoot = Join-Path $dataRoot 'Managed'
    $moduleRoot = Join-Path $managedRoot 'UnityEngine'
    $standardRoot = Join-Path $dataRoot 'NetStandard'
    $frameworkReferences = @(Find-ReferenceAssemblies -Directories @(
        (Join-Path $standardRoot 'ref\2.1.0'),
        (Join-Path $standardRoot 'compat\2.1.0\shims\netstandard')
    ) -Filter '*.dll')
    if (-not ($frameworkReferences | Where-Object { [IO.Path]::GetFileName($_) -eq 'netstandard.dll' })) {
        throw 'Unity .NET Standard 2.1 reference assemblies were not found.'
    }
    $runtimeReferences = @($frameworkReferences) + @(Find-ReferenceAssemblies -Directories @(
        $moduleRoot, $managedRoot
    ) -Filter 'UnityEngine*.dll')
    $runtimeReferences += @(Find-ReferenceAssemblies -Directories @(
        $moduleRoot, $managedRoot
    ) -Filter 'Unity.Scripting.dll')
    $editorReferences = @($runtimeReferences) + @(Find-ReferenceAssemblies -Directories @(
        $moduleRoot, (Join-Path $managedRoot 'UnityEditor'), $managedRoot
    ) -Filter 'UnityEditor*.dll')
    $runtimeSources = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'Assets\ControlLab\Scripts') -Recurse -File -Filter '*.cs' |
        Sort-Object FullName | Select-Object -ExpandProperty FullName)
    $editorSources = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot 'Assets\ControlLab\Editor') -Recurse -File -Filter '*.cs' |
        Sort-Object FullName | Select-Object -ExpandProperty FullName)
    $symbols = @('UNITY_6000_5_OR_NEWER', 'UNITY_6000_5', 'UNITY_6000',
        'UNITY_STANDALONE', 'UNITY_STANDALONE_WIN', 'ENABLE_LEGACY_INPUT_MANAGER', 'NET_STANDARD_2_1')
    $report.unityEditor = $editorPath
    $report.compiler = $compilerPath
    $report.framework = '.NET Standard 2.1'
    $runtimeAssembly = Invoke-SourceCheck -Name 'ControlLab.Runtime.SourceCheck' -Sources $runtimeSources `
        -References $runtimeReferences -Symbols $symbols
    Invoke-SourceCheck -Name 'ControlLab.Editor.SourceCheck' -Sources $editorSources `
        -References ($editorReferences + @($runtimeAssembly)) -Symbols ($symbols + @('UNITY_EDITOR', 'UNITY_EDITOR_WIN')) | Out-Null
    $report.success = $true
    Write-Host 'Source type-check passed. This is not a Unity import, runtime test, or Player build.'
}
catch {
    $report.error = $_.Exception.Message
    throw
}
finally {
    $report.finishedUtc = [DateTime]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    Write-Host "Report: $reportPath"
}
