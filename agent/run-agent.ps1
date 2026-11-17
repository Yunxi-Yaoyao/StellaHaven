# Scheduled Task entry point. Credentials are loaded from an ACL-protected file,
# never passed on the PowerShell/Python command line or printed here.
param([string]$ConfigPath = (Join-Path $PSScriptRoot 'private-config.json'))
$ErrorActionPreference = 'Stop'
try {
    if ([IO.Path]::GetFullPath($ConfigPath) -ine (Join-Path $PSScriptRoot 'private-config.json')) { throw 'Foreign config path refused' }
    $config = [IO.File]::ReadAllText($ConfigPath) | ConvertFrom-Json
    if (-not $config.STELLA_URL -or -not $config.STELLA_TOKEN -or
        -not [IO.Path]::IsPathRooted($config.PythonPath) -or
        -not (Test-Path -LiteralPath $config.PythonPath -PathType Leaf)) {
        throw 'Invalid private configuration'
    }
    if ($config.STELLA_INSTANCE_ID) {
        if ($config.STELLA_INSTANCE_ID -cnotmatch '^[a-f0-9]{24}$' -or
            [IO.Path]::GetFullPath([string]$config.STELLA_INSTANCE_MANIFEST) -ine (Join-Path $PSScriptRoot 'instance.json')) { throw 'Invalid installation binding' }
        $manifest = [IO.File]::ReadAllText($config.STELLA_INSTANCE_MANIFEST) | ConvertFrom-Json
        if ($manifest.instance_id -cne $config.STELLA_INSTANCE_ID) { throw 'Installation binding mismatch' }
        $env:STELLA_INSTANCE_ID = [string]$config.STELLA_INSTANCE_ID
        $env:STELLA_INSTANCE_MANIFEST = [string]$config.STELLA_INSTANCE_MANIFEST
    }
    $env:STELLA_URL = [string]$config.STELLA_URL
    $env:STELLA_TOKEN = [string]$config.STELLA_TOKEN
    $env:STELLA_HARDWARE_SENSORS_FILE = [string]$config.STELLA_HARDWARE_SENSORS_FILE
    Set-Location $PSScriptRoot
    & $config.PythonPath -u (Join-Path $PSScriptRoot 'stella_agent.py')
    # A resident agent exiting cleanly is still unexpected; trigger task restart.
    $result = $LASTEXITCODE
    if ($result -eq 0) { $result = 1 }
    exit $result
} catch {
    # Do not emit the exception/config: it may contain credentials.
    Write-Error 'StellaAgent failed to start or stopped; check the private config and Python runtime.' -ErrorAction Continue
    exit 1
}
