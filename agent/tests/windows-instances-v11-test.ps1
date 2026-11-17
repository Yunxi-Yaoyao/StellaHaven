# Windows PowerShell 5.1. All ScheduledTasks writes are mocked before installer use.
# No driver, dependencies, downloads, real task writes, or resident process stops.
param([string]$AgentDir = (Split-Path $PSScriptRoot -Parent), [string]$PythonPath)
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks, CimCmdlets, Microsoft.PowerShell.Security, Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility -ErrorAction Stop
$PSModuleAutoLoadingPreference = 'None'
$realBefore = @(ScheduledTasks\Get-ScheduledTask | Where-Object { $_.TaskName -match '^Stella' } | ForEach-Object { ScheduledTasks\Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath }) -join "`n"
foreach ($name in @('install.ps1','run-agent.ps1','hardware-sensors.ps1')) {
    $errors = $null; $tokens = $null
    [Management.Automation.Language.Parser]::ParseFile((Join-Path $AgentDir $name),[ref]$tokens,[ref]$errors) | Out-Null
    if ($errors.Count) { throw "AST failed: $name" }
}
. (Join-Path $AgentDir 'install.ps1')
if (-not $PythonPath) { $PythonPath = (Get-Command python -CommandType Application | Select-Object -First 1).Source }
# All fixture writes remain beneath the caller's disposable QA source tree.
$root = Join-Path $AgentDir ('.fixture-v11-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
# Generated uninstall scripts have their own script scope and a local $tasks array.
# Process-global fixture state keeps their mocks attached to this same fake store.
$global:StellaV11counts = @{}; $global:StellaV11assertions = 0
$global:StellaV11tasks = @{}; $global:StellaV11stops = @(); $global:StellaV11center = ('a'*64); $global:StellaV11node = 7
$global:StellaV11unauthorized = $false; $global:StellaV11failRegister = $false; $global:StellaV11corrupt = $false
function Assert($Condition,[string]$Message) { if (-not $Condition) { throw "FAIL: $Message" }; $global:StellaV11assertions++ }
function Count-Mock([string]$Name) { $global:StellaV11counts[$Name] = 1 + [int]$global:StellaV11counts[$Name] }
function Test-StellaAdministrator { return $true }
function Initialize-StellaRuntime([string]$Python,[string]$Directory,[switch]$NoDeps) { return $Python }
function Invoke-WebRequest {
    param($Uri,$Headers,$OutFile,$MaximumRedirection,[switch]$UseBasicParsing,$ErrorAction)
    Count-Mock 'Invoke-WebRequest'
    Assert ($Uri -like '*/agent/identity') 'No source download permitted'
    Assert ($Headers.Authorization -eq 'Bearer fixture-v11-token') 'Real bearer value is required'
    if ($global:StellaV11unauthorized) { throw '401 fixture' }
    $source = Get-Item -LiteralPath (Join-Path $AgentDir 'stella_agent.py')
    return [pscustomobject]@{ StatusCode=200; Content=(@{ center_id=$global:StellaV11center; node_id=$global:StellaV11node; source_version='0.6.18'; source_sha256=(Get-FileHash $source.FullName).Hash.ToLowerInvariant(); source_size=[int]$source.Length } | ConvertTo-Json -Compress) }
}
function Get-StellaSource([string]$Name,[string]$Endpoint,[string]$Stage,[string]$SourceDir,[string]$Url) {
    $target = Join-Path $Stage $Name
    Copy-Item -LiteralPath (Join-Path $SourceDir $Name) -Destination $target
    if ($global:StellaV11corrupt -and $Name -eq 'stella_agent.py') { Add-Content -LiteralPath $target -Value '# mismatched source' }
    return $target
}
function Get-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction) Count-Mock 'Get-ScheduledTask'; Assert ($TaskPath -eq '\') 'Exact task root'; return $global:StellaV11tasks[$TaskName] }
function Register-ScheduledTask {
    param($TaskName,$TaskPath,$Action,$Trigger,$Principal,$Settings,[switch]$Force,$Xml,$ErrorAction)
    Count-Mock 'Register-ScheduledTask'
    Assert ($TaskPath -eq '\') 'Exact register task root'
    if ($Xml) { $global:StellaV11tasks[$TaskName] = $global:StellaV11oldTask; return }
    if ($global:StellaV11failRegister -and $TaskName -like 'StellaAgent-*') { $global:StellaV11failRegister = $false; throw 'fixture registration failure' }
    $global:StellaV11tasks[$TaskName] = [pscustomobject]@{ TaskName=$TaskName;TaskPath=$TaskPath;Actions=@($Action);Principal=$Principal;Settings=$Settings;State='Ready' }
}
function Start-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction) Count-Mock 'Start-ScheduledTask'; Assert ($TaskPath -eq '\') 'Exact start task root' }
function Stop-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction) Count-Mock 'Stop-ScheduledTask'; Assert ($TaskPath -eq '\') 'Exact stop task root'; $global:StellaV11stops += $TaskName; $global:StellaV11tasks[$TaskName].State='Ready' }
function Unregister-ScheduledTask { param($TaskName,$TaskPath,$Confirm,$ErrorAction) Count-Mock 'Unregister-ScheduledTask'; Assert ($TaskPath -eq '\') 'Exact unregister root'; $global:StellaV11tasks.Remove($TaskName) }
function Export-ScheduledTask { param($TaskName,$TaskPath,$ErrorAction) Count-Mock 'Export-ScheduledTask'; $global:StellaV11oldTask=$global:StellaV11tasks[$TaskName]; return '<fixture/>' }
function Get-CimInstance { param($ClassName,$ErrorAction) Count-Mock 'Get-CimInstance'; return @() }
foreach ($name in @('Register-ScheduledTask','Start-ScheduledTask','Stop-ScheduledTask','Unregister-ScheduledTask','Get-CimInstance','Invoke-WebRequest')) {
    Assert ((Get-Command $name).CommandType -eq 'Function') "side-effect mock missing: $name"
}
function Snapshot([string]$Path) {
    return (@(Get-ChildItem -LiteralPath $Path -File -Recurse -Force | Sort-Object FullName | ForEach-Object { $_.FullName + ':' + (Get-FileHash -LiteralPath $_.FullName).Hash }) -join "`n")
}
try {
    $a = Join-Path $root 'A'; $b = Join-Path $root 'B'
    Invoke-StellaInstall -Url 'https://one.invalid' -Token 'fixture-v11-token' -InstallDir $a -SourceDir $AgentDir -PythonPath $PythonPath -NoDeps
    $bindingA = Get-StellaInstallationBinding 'https://two.invalid' 'fixture-v11-token'
    $taskA = 'StellaAgent-' + $bindingA.instance_id
    Assert ($global:StellaV11tasks.Count -eq 1 -and $global:StellaV11tasks.ContainsKey($taskA)) 'Instance-scoped agent task'
    $channelCache = Join-Path $a 'report-channel-cache.json'
    [IO.File]::WriteAllText($channelCache, '{"installed":"https://one.invalid","sequence":41,"binding":"fixture"}')
    $channelHash = (Get-FileHash -LiteralPath $channelCache).Hash
    Invoke-StellaInstall -Url 'https://two.invalid' -Token 'fixture-v11-token' -InstallDir $a -SourceDir $AgentDir -PythonPath $PythonPath -NoDeps
    Assert ($global:StellaV11tasks.Count -eq 1) 'Same center/two origins idempotent'
    $repaired = [IO.File]::ReadAllText((Join-Path $a 'private-config.json')) | ConvertFrom-Json
    Assert ($repaired.STELLA_URL -ceq 'https://one.invalid') 'Same-center alias repair preserves installed reporting URL'
    Assert ($repaired.STELLA_TOKEN -ceq 'fixture-v11-token') 'Alias repair preserves token binding'
    Assert ((Get-FileHash -LiteralPath $channelCache).Hash -ceq $channelHash) 'Alias repair preserves channel cache and sequence'
    $before = Snapshot $a; $global:StellaV11node = 8; $failed = $false
    try { Invoke-StellaInstall -Url 'https://two.invalid' -Token 'fixture-v11-token' -InstallDir $a -SourceDir $AgentDir -PythonPath $PythonPath -NoDeps } catch { $failed = $true }
    Assert ($failed -and (Snapshot $a) -eq $before) 'Different node cannot rebind default'
    $global:StellaV11node = 7; $global:StellaV11center = ('b'*64)
    Invoke-StellaInstall -Url 'https://other.invalid' -Token 'fixture-v11-token' -InstallDir $b -SourceDir $AgentDir -PythonPath $PythonPath -NoDeps
    Assert ($global:StellaV11tasks.Count -eq 2 -and (Snapshot $a) -eq $before) 'Different centers coexist'
    $otherBefore = Snapshot $b; $global:StellaV11center = ('a'*64)
    foreach ($mode in @('unauthorized','corrupt','failRegister')) {
        Set-Variable -Scope Global -Name ('StellaV11' + $mode) -Value $true
        $failed = $false
        try { Invoke-StellaInstall -Url 'https://one.invalid' -Token 'fixture-v11-token' -InstallDir $a -SourceDir $AgentDir -PythonPath $PythonPath -NoDeps } catch { $failed = $true }
        Set-Variable -Scope Global -Name ('StellaV11' + $mode) -Value $false
        Assert ($failed -and (Snapshot $a) -eq $before -and (Snapshot $b) -eq $otherBefore) "Failure rollback preserves both centers: $mode"
    }
    $mutex = New-Object Threading.Mutex($false, ('Global\StellaInstall-' + $bindingA.instance_id))
    # Another process is needed to exercise contention; native Linux test covers it.
    $mutex.Dispose()
    $remove = Join-Path $a 'uninstall-instance.ps1'
    Test-StellaPowerShell $remove
    & $remove
    & $remove -Run
    Assert (-not (Test-Path -LiteralPath $a)) 'Own instance removed'
    Assert ((Snapshot $b) -eq $otherBefore -and $global:StellaV11tasks.Count -eq 1) 'Other center task/files survive removal'
    Assert (@($global:StellaV11stops | Where-Object { $_ -in @('StellaAgent','StellaHardwareSensors') }).Count -eq 0) 'No legacy task stopped'
    Write-Output 'PASS: actual AST; same center/two origins; different centers; node mismatch; auth/hash failure; rollback; exact instance removal'
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    $realAfter = @(ScheduledTasks\Get-ScheduledTask | Where-Object { $_.TaskName -match '^Stella' } | ForEach-Object { ScheduledTasks\Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath }) -join "`n"
    Assert ($realAfter -ceq $realBefore) 'Real Stella task definitions changed!'
    Write-Output ('RESULT_JSON:' + (@{ assertions=$global:StellaV11assertions; mock_calls=$global:StellaV11counts; real_task_definitions_unchanged=($realAfter -ceq $realBefore); fixture_removed=(-not (Test-Path -LiteralPath $root)) } | ConvertTo-Json -Depth 4 -Compress))
    Remove-Variable -Scope Global -Name StellaV11counts,StellaV11assertions,StellaV11tasks,StellaV11stops,StellaV11center,StellaV11node,StellaV11unauthorized,StellaV11failRegister,StellaV11corrupt,StellaV11oldTask -ErrorAction SilentlyContinue
}
