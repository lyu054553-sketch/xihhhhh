[CmdletBinding()]
param(
    [string]$ApiBase = $env:AGENT_API_BASE,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$ListenHost = '127.0.0.1',
    [string]$Database,
    [switch]$DemoSession,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$pythonExecutable = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pythonPrefix = @()
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonExecutable = $pythonCommand.Source
    } else {
        $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
        if (-not $pythonCommand) { throw 'Install Python 3.10 or newer to start the application.' }
        $pythonExecutable = $pythonCommand.Source
        $pythonPrefix = @('-3')
    }
}

& $pythonExecutable @pythonPrefix -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }

$applicationArguments = @((Join-Path $PSScriptRoot 'scripts\run_local.py'), '--host', $ListenHost, '--port', [string]$Port)
if ($ApiBase) { $applicationArguments += @('--api-base', $ApiBase) }
if ($PSBoundParameters.ContainsKey('Database')) { $applicationArguments += @('--database', $Database) }
if ($DemoSession) { $applicationArguments += '--demo-session' }
if ($Check) { $applicationArguments += '--check' }

& $pythonExecutable @pythonPrefix @applicationArguments
if ($LASTEXITCODE -ne 0) { throw ('Application command exited with code {0}.' -f $LASTEXITCODE) }
