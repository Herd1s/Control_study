<#
.SYNOPSIS
Build a Unity-specific Windows installer and GitHub release assets without publishing.
#>
[CmdletBinding()]
param([string]$UnityEditorPath, [string]$Iscc, [switch]$SkipPlayerBuild)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $SkipPlayerBuild) {
    & (Join-Path $PSScriptRoot 'Build-Windows.ps1') -UnityEditorPath $UnityEditorPath
}
$versionSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Assets\ControlLab\Scripts\AppVersion.cs') -Raw
$versionMatch = [regex]::Match($versionSource, 'const\s+string\s+Current\s*=\s*"(\d+\.\d+\.\d+)"')
if (-not $versionMatch.Success) { throw 'AppVersion.Current must contain a stable X.Y.Z version.' }
$releaseVersion = $versionMatch.Groups[1].Value
$payload = Join-Path $PSScriptRoot 'Builds\Windows'
$buildInfoPath = Join-Path $payload 'build-info.json'
if (-not (Test-Path -LiteralPath $buildInfoPath)) { throw 'Build marker is missing. Rebuild this Unity version before packaging.' }
$buildInfo = Get-Content -LiteralPath $buildInfoPath -Raw | ConvertFrom-Json
$assemblyPath = Join-Path $payload 'ControlLab Unity_Data\Managed\Assembly-CSharp.dll'
if ($buildInfo.productId -ne 'controllab-unity' -or $buildInfo.platform -ne 'windows-x64' -or $buildInfo.version -ne $releaseVersion) {
    throw 'The built Player product/version does not match AppVersion.Current.'
}
if ((Get-FileHash -LiteralPath $assemblyPath -Algorithm SHA256).Hash -ine $buildInfo.managedAssemblySha256) {
    throw 'The Player assembly changed after the verified build. Rebuild before packaging.'
}
foreach ($required in @('ControlLab Unity.exe','UnityPlayer.dll','MonoBleedingEdge','ControlLab Unity_Data')) {
    if (-not (Test-Path -LiteralPath (Join-Path $payload $required))) { throw "Player payload incomplete: $required" }
}

if (-not $Iscc) {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { $Iscc = $command.Source }
}
if (-not $Iscc) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    $Iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc -PathType Leaf)) {
    throw 'Inno Setup 6 compiler not found. Install it or pass -Iscc with its absolute path.'
}
$releaseDirectory = Join-Path $PSScriptRoot ('Builds\Releases\' + $releaseVersion)
New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
$iss = Join-Path $PSScriptRoot 'Packaging\Windows\ControlLabUnity.iss'
& $Iscc '/Qp' ("/DAppVersion=$releaseVersion") ("/DPayloadDir=$payload") ("/DReleaseDir=$releaseDirectory") $iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed: $LASTEXITCODE" }
$installerName = "ControlLab-Unity-Setup-$releaseVersion.exe"
$installer = Get-Item -LiteralPath (Join-Path $releaseDirectory $installerName)
if ($installer.Length -le 0) { throw 'Installer is empty.' }
$manifest = [ordered]@{
    schema = 1
    productId = 'controllab-unity'
    platform = 'windows-x64'
    version = $releaseVersion
    assetName = $installerName
    size = $installer.Length
    sha256 = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
[IO.File]::WriteAllText((Join-Path $releaseDirectory 'unity-update.json'), ($manifest | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$archive = Join-Path $releaseDirectory "ControlLab-Unity-Portable-$releaseVersion-windows-x64.zip"
Compress-Archive -Path (Join-Path $payload '*') -DestinationPath $archive -Force
$checksums = foreach ($file in @($installer.FullName, $archive, (Join-Path $releaseDirectory 'unity-update.json'))) {
    (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + [IO.Path]::GetFileName($file)
}
[IO.File]::WriteAllLines((Join-Path $releaseDirectory 'SHA256SUMS'), [string[]]$checksums, [Text.UTF8Encoding]::new($false))
Write-Output "Release assets built: $releaseDirectory"
Write-Output "Tag contract: unity-v$releaseVersion. Nothing was uploaded or published."
