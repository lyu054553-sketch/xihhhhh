[CmdletBinding()]
param(
    [ValidateSet('demo', 'real')]
    [string]$Mode = 'demo',
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$Database,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw 'Create the local environment first: py -3 -m venv .venv; then .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
}

& $pythonExecutable -c 'import fastapi, uvicorn, pydantic, openpyxl'
if ($LASTEXITCODE -ne 0) {
    throw 'Dependencies are missing. Run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt'
}

$localApplicationData = [Environment]::GetFolderPath('LocalApplicationData')
if (-not $localApplicationData) { throw 'LocalApplicationData is unavailable.' }
$demoDirectory = [IO.Path]::GetFullPath((Join-Path $localApplicationData 'InventoryCashAgent\zmj\demo'))
if ($Mode -eq 'demo') {
    if ($Database) { throw '-Database is only accepted with -Mode real. Demo always uses its own isolated database.' }
    $databasePath = Join-Path $demoDirectory 'inventory.db'
} else {
    if (-not $Database) { throw 'Real mode requires -Database with an existing imported SQLite file.' }
    $databasePath = (Resolve-Path -LiteralPath $Database).ProviderPath
    if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) { throw 'The database must be an existing file.' }
    $repositoryPrefix = [IO.Path]::GetFullPath($projectDirectory).TrimEnd('\') + '\'
    if ($databasePath.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Keep real databases outside the web project directory because it is served as static content.'
    }
    if ($databasePath.StartsWith($demoDirectory.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The isolated demo directory cannot be used for real data.'
    }
    @'
import pathlib
import sqlite3
import sys

with sqlite3.connect(pathlib.Path(sys.argv[1]).as_uri() + '?mode=ro', uri=True) as database:
    row = database.execute('SELECT COUNT(*) FROM real_inventory_snapshots WHERE tenant_id=?', ('demo',)).fetchone()
    sys.exit(0 if row[0] else 1)
'@ | & $pythonExecutable - $databasePath
    if ($LASTEXITCODE -ne 0) { throw 'This file has no imported real inventory snapshot for the default tenant.' }
}

Write-Host ('Mode: {0}' -f $Mode)
Write-Host ('Database: {0}' -f $databasePath)
Write-Host ('URL: http://127.0.0.1:{0}' -f $Port)
Write-Host 'No packages are installed and no database is reset by this launcher.'
if ($Check) { return }

if ($Mode -eq 'demo') {
    New-Item -ItemType Directory -Path $demoDirectory -Force | Out-Null
}
$previousEnvironment = @{}
foreach ($name in @('INVENTORY_AGENT_MODE', 'INVENTORY_AGENT_DB', 'PORT', 'PYTHONUTF8')) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location $projectDirectory
try {
    $env:INVENTORY_AGENT_MODE = $Mode
    $env:INVENTORY_AGENT_DB = $databasePath
    $env:PORT = [string]$Port
    $env:PYTHONUTF8 = '1'
    & $pythonExecutable server.py
    if ($LASTEXITCODE -ne 0) { throw ('The server exited with code {0}.' -f $LASTEXITCODE) }
} finally {
    Pop-Location
    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
