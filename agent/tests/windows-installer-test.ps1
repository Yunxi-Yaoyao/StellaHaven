# Native Windows PowerShell 5.1 tests. No production task/path writes.
# Default: HTTP/task mocks only; -DependencySmoke permits real PyPI installs
# solely in the disposable fixture venv. LibraryZip is read-only.
param([string]$AgentDir = (Split-Path $PSScriptRoot -Parent), [string]$LibraryZip = 'C:\stella-agent\LibreHardwareMonitor.zip', [switch]$DependencySmoke)
$ErrorActionPreference = 'Stop'
# Import BEFORE defining mocks: lazy module import overwrites same-name functions.
Import-Module ScheduledTasks, Microsoft.PowerShell.Security, Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility, Microsoft.PowerShell.Archive -ErrorAction Stop
$PSModuleAutoLoadingPreference = 'None'
$beforeTasks = @(ScheduledTasks\Get-ScheduledTask -ErrorAction Stop | Where-Object TaskName -in @('StellaAgent','StellaHardwareSensors') | ForEach-Object { ScheduledTasks\Export-ScheduledTask -TaskName $_.TaskName }) -join "`n"
$installer = Join-Path $AgentDir 'install.ps1'
$ast = [Management.Automation.Language.Parser]::ParseFile($installer, [ref]$null, [ref]$null)
if (-not $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-StellaInstall' }, $true)) {
    throw 'FAIL: installer must expose Invoke-StellaInstall for isolated failure-gate tests'
}
. $installer
$root = Join-Path $env:LOCALAPPDATA ('StellaInstallerTests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root | Out-Null
$script:Registered = @()
$script:Started = @()
$script:Stopped = @()
$script:ExistingTasks = @()
$script:HttpStatus = 401
$script:HttpThrows = $false
$script:DownloadSources = $null
$script:DownloadRequests = @()
function Read-Host { param($Prompt) return 'n' }
function Test-StellaAdministrator { return $true }
function Invoke-WebRequest {
    param($Uri, $Headers, $OutFile, $MaximumRedirection, [switch]$UseBasicParsing, [switch]$PassThru, $ErrorAction)
    if ($script:HttpThrows) { throw 'fixture transport failure' }
    if ($Uri -notlike '*/agent/config') {
        if (-not $script:DownloadSources) { throw 'No source downloads allowed in this test' }
        $name = if ($Uri -like '*/agent/script') { 'stella_agent.py' } else { ($Uri -split '/')[-1] }
        Assert (-not $Headers) 'public source download must not send credentials'
        $script:DownloadRequests += $Uri
        Copy-Item (Join-Path $script:DownloadSources $name) $OutFile -Force
        return [pscustomobject]@{ StatusCode=200 }
    }
    return [pscustomobject]@{ StatusCode = $script:HttpStatus; Content = '{"node_id":1}' }
}
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Settings, $Principal, [switch]$Force)
    $script:Registered += [pscustomobject]@{ TaskName=$TaskName; Actions=@($Action); Triggers=@($Trigger); Settings=$Settings; Principal=$Principal; State='Ready' }
}
function Get-ScheduledTask { param($TaskName, $ErrorAction) return (@($script:ExistingTasks + $script:Registered) | Where-Object TaskName -eq $TaskName | Select-Object -Last 1) }
function Stop-ScheduledTask { param($TaskName, $ErrorAction) $script:Stopped += $TaskName }
function Start-ScheduledTask { param($TaskName) $script:Started += $TaskName }
function Assert($Condition, [string]$Message) { if (-not $Condition) { throw "FAIL: $Message" } }
function Invoke-TestWrapper([string]$Wrapper) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $info.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $Wrapper + '"'
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [pscustomobject]@{ Code=$process.ExitCode; Stdout=$stdout; Stderr=$stderr }
}
foreach ($name in @('Register-ScheduledTask','Start-ScheduledTask','Stop-ScheduledTask','Get-ScheduledTask','Invoke-WebRequest')) {
    Assert ((Get-Command $name).CommandType -eq 'Function') "side-effect mock was overwritten: $name"
}
try {
    Assert (-not (Confirm-StellaDependencies)) 'default dependency install must respect an interactive no'
    Assert (Confirm-StellaDependencies -Deps) 'Deps explicitly permits isolated dependency install'
    Assert (-not (Confirm-StellaDependencies -NoDeps)) 'NoDeps never installs dependencies'
    $target = Join-Path $root 'installed'
    New-Item -ItemType Directory $target | Out-Null
    $existing = Join-Path $target 'stella_agent.py'
    [IO.File]::WriteAllText($existing, '# existing agent')
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $AgentDir -InstallDir $target }
    catch { $failed = $true }
    Assert $failed 'HTTP 401 must abort'
    Assert ((Get-Content $existing -Raw) -eq '# existing agent') 'failed validation must preserve existing source'
    Assert ($script:Registered.Count -eq 0 -and $script:Started.Count -eq 0) 'failed validation must not register or start tasks'
    Write-Output 'PASS: HTTP 401 preserves installed source and tasks'
    foreach ($status in @(201, 302, 403, 500)) {
        $script:HttpStatus = $status
        $failed = $false
        try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $AgentDir -InstallDir $target }
        catch { $failed = $true }
        Assert $failed "HTTP $status must abort"
    }
    $script:HttpStatus = 200
    $script:HttpThrows = $true
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $AgentDir -InstallDir $target }
    catch { $failed = $true }
    Assert $failed 'network failure must abort rather than skip token validation'
    $script:HttpThrows = $false
    $fixture = Join-Path $root 'source'
    New-Item -ItemType Directory $fixture | Out-Null
    [IO.File]::WriteAllText((Join-Path $fixture 'stella_agent.py'), 'def invalid syntax:')
    [IO.File]::WriteAllText((Join-Path $fixture 'run-agent.ps1'), 'Write-Output fixture')
    $python = (Get-Command python).Source
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python }
    catch { $failed = $true }
    Assert $failed 'invalid Python syntax must abort'
    Assert ((Get-Content $existing -Raw) -eq '# existing agent') 'invalid Python must preserve existing agent'
    Assert ($script:Registered.Count -eq 0 -and $script:Started.Count -eq 0) 'invalid source must not touch tasks'
    Write-Output 'PASS: non-200 and Python syntax failure gates'
    [IO.File]::WriteAllText((Join-Path $fixture 'stella_agent.py'), 'print("fixture")')
    [IO.File]::WriteAllText((Join-Path $fixture 'run-agent.ps1'), 'param(')
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python }
    catch { $failed = $true }
    Assert $failed 'invalid wrapper PowerShell must abort'
    [IO.File]::WriteAllText((Join-Path $fixture 'stella_agent.py'), '')
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python }
    catch { $failed = $true }
    Assert $failed 'empty Python source must abort'
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -InstallDir $target -PythonPath $python }
    catch { $failed = $true }
    Assert $failed 'source download failure must abort'
    Assert ((Get-Content $existing -Raw) -eq '# existing agent') 'all source failures preserve old agent'
    Assert ($script:Registered.Count -eq 0 -and $script:Started.Count -eq 0 -and $script:Stopped.Count -eq 0) 'all source failures leave tasks untouched'
    [IO.File]::WriteAllText((Join-Path $fixture 'stella_agent.py'), 'print("fixture")')
    Copy-Item (Join-Path $AgentDir 'run-agent.ps1') (Join-Path $fixture 'run-agent.ps1') -Force -ErrorAction SilentlyContinue
    Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python
    Assert ($script:Registered.Count -eq 1 -and $script:Started.Count -eq 1) "valid local source must install and start exactly StellaAgent (registered=$($script:Registered.Count), started=$($script:Started.Count))"
    $task = $script:Registered[0]
    Assert ($task.TaskName -eq 'StellaAgent' -and $task.Principal.UserId -eq 'SYSTEM') 'explicit SYSTEM principal'
    Assert ($task.Principal.RunLevel -eq 1 -and $task.Principal.LogonType -eq 5) 'highest ServiceAccount principal'
    Assert ($task.Triggers[0].CimClass.CimClassName -eq 'MSFT_TaskBootTrigger') 'boot trigger'
    Assert ($task.Settings.ExecutionTimeLimit -eq 'PT0S' -and $task.Settings.RestartCount -eq 999) 'unlimited lifetime and crash restart'
    Assert ($task.Settings.RestartInterval -eq 'PT1M' -and $task.Settings.MultipleInstances -eq 2) 'one-minute restart and IgnoreNew'
    Assert (-not $task.Settings.DisallowStartIfOnBatteries -and -not $task.Settings.StopIfGoingOnBatteries) 'resident task must survive battery power'
    Assert ([IO.Path]::IsPathRooted($task.Actions[0].Execute)) 'absolute scheduled executable'
    Assert ($task.Actions[0].Arguments -notmatch 'fixture-secret|--token|-Token|--url') 'task arguments contain no credentials'
    $configFile = Join-Path $target 'private-config.json'
    Assert (Test-Path $configFile) 'private config is written'
    $config = Get-Content $configFile -Raw | ConvertFrom-Json
    Assert ($config.STELLA_TOKEN -eq 'fixture-secret' -and $config.STELLA_URL -eq 'https://stella.invalid') 'config retains exact credentials'
    Assert ([IO.Path]::IsPathRooted($config.PythonPath)) 'runtime uses absolute Python path'
    Assert ($config.PythonPath -eq (Join-Path $target 'venv\Scripts\python.exe')) 'runtime must use isolated venv, including NoDeps mode'
    $prefixCheck = & $config.PythonPath -c 'import sys; print(sys.prefix != sys.base_prefix)'
    Assert ($prefixCheck -eq 'True') 'runtime really is a venv'
    foreach ($path in @($configFile, $target)) {
        $acl = Get-Acl $path
        Assert $acl.AreAccessRulesProtected 'private ACL must not inherit user permissions'
        $sids = @($acl.Access | ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } | Sort-Object -Unique)
        Assert ($sids.Count -eq 2 -and 'S-1-5-18' -in $sids -and 'S-1-5-32-544' -in $sids) 'only SYSTEM and Administrators may access config/install dir'
    }
    Write-Output 'PASS: local install, SYSTEM boot/restart, private config and credential-free task'
    $script:ExistingTasks = @($script:Registered)
    $script:Registered = @(); $script:Started = @()
    $beforeSource = Get-Content $existing -Raw
    Copy-Item (Join-Path $AgentDir 'hardware-sensors.ps1') (Join-Path $fixture 'hardware-sensors.ps1') -Force
    [IO.File]::WriteAllText((Join-Path $fixture 'LibreHardwareMonitor.zip'), 'invalid zip')
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python -HardwareSensors }
    catch { $failed = $true }
    Assert $failed 'opt-in library hash mismatch must abort'
    Assert ($script:Registered.Count -eq 0 -and $script:Started.Count -eq 0 -and $script:Stopped.Count -eq 0) 'hash mismatch must not touch tasks'
    Assert ((Get-Content $existing -Raw) -eq $beforeSource) 'hash mismatch must preserve source'
    Copy-Item $LibraryZip (Join-Path $fixture 'LibreHardwareMonitor.zip') -Force
    Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python -HardwareSensors
    Assert ($script:Registered.Count -eq 2 -and $script:Started.Count -eq 2) 'explicit opt-in must start agent and hardware bridge'
    Assert ('StellaAgent' -in $script:Stopped) 'upgrade must stop the old task before replacing its runtime'
    $sensorTask = $script:Registered | Where-Object TaskName -eq 'StellaHardwareSensors'
    Assert ($sensorTask.Principal.UserId -eq 'SYSTEM' -and $sensorTask.Settings.ExecutionTimeLimit -eq 'PT0S') 'bridge is SYSTEM resident'
    Assert ($sensorTask.Actions[0].Arguments -match '-IntervalSeconds 30' -and $sensorTask.Actions[0].Arguments -match 'hardware-sensors.ps1') 'bridge writes JSON every 30 seconds'
    Assert ($sensorTask.Actions[0].Arguments -notmatch 'fixture-secret|LibreHardwareMonitor.exe|--token') 'bridge never launches GUI or receives credentials'
    Assert (Test-Path (Join-Path $target 'LibreHardwareMonitor\LibreHardwareMonitorLib.dll')) 'verified official library extracted'
    Assert ((Get-FileHash (Join-Path $target 'LibreHardwareMonitor.zip')).Hash -eq '086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001') 'installed archive keeps pinned hash'
    Write-Output 'PASS: explicit hardware opt-in, official SHA256 and SYSTEM JSON task'
    $savedToken = $env:STELLA_TOKEN
    try {
        $env:STELLA_TOKEN = 'fixture-secret'
        Invoke-StellaInstall -Url 'https://stella.invalid' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python
    } finally { $env:STELLA_TOKEN = $savedToken }
    Write-Output 'PASS: env-only token input needs no credential in installer argv'
    Assert ($script:DownloadRequests.Count -eq 0) 'SourceDir performs no script downloads, including opt-in bridge/archive'
    $script:DownloadSources = $fixture
    Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -InstallDir $target -PythonPath $python
    Assert ($script:DownloadRequests.Count -eq 2 -and 'https://stella.invalid/agent/script' -in $script:DownloadRequests -and 'https://stella.invalid/agent/run-agent.ps1' -in $script:DownloadRequests) 'online mode downloads only agent and wrapper without hardware opt-in'
    $script:DownloadSources = $null
    Write-Output 'PASS: staged online downloads and strict opt-in source selection'
    $fakeAgent = @'
import os, sys
assert len(sys.argv) == 1
assert os.environ['STELLA_TOKEN'] == 'fixture-secret'
assert os.environ['STELLA_URL'] == 'https://stella.invalid'
assert os.environ['STELLA_HARDWARE_SENSORS_FILE'].endswith('hardware-sensors.json')
print('WRAPPER_OK')
sys.exit(7)
'@
    [IO.File]::WriteAllText($existing, $fakeAgent)
    $result = Invoke-TestWrapper (Join-Path $target 'run-agent.ps1')
    Assert ($result.Code -eq 7 -and $result.Stdout.Trim() -eq 'WRAPPER_OK') 'actual wrapper loads environment and preserves nonzero Python exit status'
    Assert (($result.Stdout + $result.Stderr) -notmatch 'fixture-secret') 'wrapper does not print the token'
    [IO.File]::WriteAllText($existing, 'pass')
    $result = Invoke-TestWrapper (Join-Path $target 'run-agent.ps1')
    Assert ($result.Code -eq 1) 'unexpected clean agent exit requests task restart'
    $validConfig = [IO.File]::ReadAllText($configFile)
    [IO.File]::WriteAllText($configFile, '{"STELLA_TOKEN":"fixture-secret","PythonPath":"missing"}')
    $result = Invoke-TestWrapper (Join-Path $target 'run-agent.ps1')
    Assert ($result.Code -eq 1 -and $result.Stderr -notmatch 'fixture-secret') 'invalid private config fails without leaking token'
    [IO.File]::WriteAllText($configFile, $validConfig)
    Write-Output 'PASS: real wrapper process environment, exit/restart behavior and no credential output'
    if ($DependencySmoke) {
        $dependencyDir = Join-Path $root 'dependency-smoke'
        New-Item -ItemType Directory -Path $dependencyDir | Out-Null
        Set-StellaPrivateAcl $dependencyDir
        $runtime = Initialize-StellaRuntime $python $dependencyDir
        & $runtime -c "import httpx,psutil,sys; assert sys.prefix != sys.base_prefix; print('DEPENDENCIES_OK')"
        Assert ($LASTEXITCODE -eq 0) 'real optional dependency install must import inside isolated venv'
        Write-Output 'PASS: real isolated ensurepip/pip/httpx/psutil dependency smoke'
    }
} finally {
    Remove-Item $root -Recurse -Force
    $afterTasks = @(ScheduledTasks\Get-ScheduledTask -ErrorAction Stop | Where-Object TaskName -in @('StellaAgent','StellaHardwareSensors') | ForEach-Object { ScheduledTasks\Export-ScheduledTask -TaskName $_.TaskName }) -join "`n"
    Assert ($beforeTasks -eq $afterTasks) 'tests must not change any real Stella scheduled task'
    Write-Output 'PASS: real scheduled task definitions unchanged'
}
