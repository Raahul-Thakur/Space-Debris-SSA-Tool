param(
    [Parameter(Mandatory = $true)][string]$DatabaseUrl,
    [string]$OutputDirectory = "backups"
)

$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$OutputDirectory"))
New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
$timestamp = Get-Date -Format "yyyyMMddTHHmmssZ"
$outputFile = Join-Path $resolvedOutput "sdebris_$timestamp.dump"

& pg_dump --format=custom --no-owner --no-privileges --file=$outputFile $DatabaseUrl
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
Write-Output $outputFile
