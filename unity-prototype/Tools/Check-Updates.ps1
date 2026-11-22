[CmdletBinding()]
param([switch]$Live)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $PSScriptRoot 'UpdateCheck\UpdateCheck.csproj'
$output = Join-Path $projectRoot 'Logs\Verification\update-check'
$arguments = @('run','--project',$project,'--configuration','Release','--',$output)
if ($Live) { $arguments += '--live' }
& dotnet @arguments
if ($LASTEXITCODE -ne 0) { throw 'Updater contract checks failed.' }
