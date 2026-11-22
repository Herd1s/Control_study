<#
.SYNOPSIS
Validate and replay the frozen reference without the retired Python project.
.DESCRIPTION
Requires system Python (standard library only) and a .NET SDK able to build net9.0.
Does not launch Unity Editor or Player. Output stays inside this Unity project.
#>
[CmdletBinding()]
param([string]$PythonCommand = 'python', [string]$DotnetCommand = 'dotnet')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$checkerRoot = Join-Path $PSScriptRoot 'PhysicsCheck'
$fixturePath = Join-Path $checkerRoot 'Fixtures\physics-golden.json'
$reportPath = Join-Path $projectRoot 'Logs\Verification\physics-verification-dotnet.json'
$modelPath = Join-Path $projectRoot 'Assets\ControlLab\Scripts\PendulumModel.cs'

& $PythonCommand (Join-Path $checkerRoot 'verify_frozen_reference.py')
if ($LASTEXITCODE -ne 0) { throw 'Frozen reference integrity check failed.' }
& $DotnetCommand run --project (Join-Path $checkerRoot 'PhysicsCheck.csproj') --configuration Release -- $fixturePath $reportPath $modelPath
if ($LASTEXITCODE -ne 0) { throw 'C# model replay did not match the frozen reference.' }
Write-Host "Numerical replay report: $reportPath"
