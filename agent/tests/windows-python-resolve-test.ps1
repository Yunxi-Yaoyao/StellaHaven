# Run on Windows with an installed Python; does not install or touch tasks.
$ErrorActionPreference = 'Stop'
$python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
. (Join-Path $PSScriptRoot '..\install.ps1')
function Get-Command {
    [pscustomobject]@{Source=$script:python},
    [pscustomobject]@{Source=(Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\python.exe')}
}
$result = Resolve-StellaPython ''
if ($result -ne $python) { throw 'Must resolve first concrete executable, not array of all PATH matches' }
Write-Output 'PASS multiple Python PATH matches select first concrete executable'
