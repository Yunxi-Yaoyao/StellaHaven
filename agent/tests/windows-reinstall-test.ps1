# Windows 5.1: all task writes mocked; only disposable directories/processes.
param([string]$AgentDir = (Split-Path $PSScriptRoot -Parent), [string]$LibraryZip = 'C:\stella-agent\LibreHardwareMonitor.zip')
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks, CimCmdlets, Microsoft.PowerShell.Security, Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility, Microsoft.PowerShell.Archive
$PSModuleAutoLoadingPreference = 'None'
$before = @(ScheduledTasks\Get-ScheduledTask | Where-Object TaskName -in @('StellaAgent','StellaHardwareSensors') | ForEach-Object { ScheduledTasks\Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath }) -join "`n"
. (Join-Path $AgentDir 'install.ps1')
function Assert($value, $message) { if (-not $value) { throw "FAIL: $message" } }
$root = Join-Path $env:LOCALAPPDATA ('StellaReinstallTests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root | Out-Null
$target = Join-Path $root 'installed'
New-Item -ItemType Directory $target | Out-Null
$script:task = $null; $script:stops = @(); $script:starts = @(); $script:polls = 0
$script:processes = @(); $script:delay = $false; $script:sensorTask = $null
function Get-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction)
    Assert ($TaskPath -eq '\') 'task lookup must use exact root task path'
    if ($script:task -and $TaskName -eq $script:task.TaskName) { return $script:task }
    if ($script:sensorTask -and $TaskName -eq $script:sensorTask.TaskName) { return $script:sensorTask }
}
function Stop-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction)
    Assert ($TaskPath -eq '\' -and $TaskName -in @('StellaAgent','StellaHardwareSensors')) 'only verified exact task may stop'
    $script:stops += $TaskName
    if (-not $script:holdState) { (Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath).State = 'Ready' }
}
function Start-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) $script:starts += $TaskName }
function Get-CimInstance { param($ClassName, $ErrorAction)
    Assert ($ClassName -eq 'Win32_Process') 'only process inventory needed'
    $script:polls++
    if ($script:holdState -and $script:polls -gt 3) { $script:task.State = 'Ready' }
    if ($script:delay -and $script:polls -gt 3) { return @() }
    if ($script:delay -and $script:polls -gt 1) { return @($script:processes | Where-Object ProcessId -eq 41002) }
    return $script:processes
}
function New-FixtureTask([string]$Name = 'StellaAgent') {
    $exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $file = if ($Name -eq 'StellaAgent') { 'run-agent.ps1' } else { 'hardware-sensors.ps1' }
    $args = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $target $file) + '"'
    if ($Name -eq 'StellaHardwareSensors') { $args += ' -IntervalSeconds 30' }
    return [pscustomobject]@{ TaskName=$Name; TaskPath='\'; State='Running'; Principal=[pscustomobject]@{UserId='SYSTEM'}; Actions=@([pscustomobject]@{Execute=$exe; Arguments=$args; WorkingDirectory=$target}) }
}
try {
    $script:task = New-FixtureTask
    $bad = New-FixtureTask
    $bad.Actions[0].Arguments = '-NoProfile -File "C:\unrelated\run-agent.ps1"'
    $failed = $false
    try { Stop-StellaResidentTask $bad $target -TimeoutSeconds 1 } catch { $failed = $true }
    Assert $failed 'foreign action must fail closed'
    Assert ($script:stops.Count -eq 0) 'foreign action must never be stopped'
    foreach ($case in @('folder','principal','executable','working-directory','extra-action','name-pattern','appended-command')) {
        $bad = New-FixtureTask
        switch ($case) {
            'folder' { $bad.TaskPath = '\Other\' }
            'principal' { $bad.Principal.UserId = 'yaoyao' }
            'executable' { $bad.Actions[0].Execute = 'C:\Python\python.exe' }
            'working-directory' { $bad.Actions[0].WorkingDirectory = 'C:\Other' }
            'extra-action' { $bad.Actions += $bad.Actions[0] }
            'name-pattern' { $bad.TaskName = 'Stella*' }
            'appended-command' { $bad.Actions[0].Arguments += '; Stop-Process -Name python' }
        }
        $failed = $false
        try { Stop-StellaResidentTask $bad $target -TimeoutSeconds 1 } catch { $failed = $true }
        Assert $failed "foreign task case rejected: $case"
        Assert ($script:stops.Count -eq 0) 'no stop for unverified task case'
    }
    Write-Output 'PASS: foreign task action/path/principal/executable/name rejected before any stop'
    $now = [datetime]::UtcNow
    $script:processes = @(
        [pscustomobject]@{ProcessId=41001; ParentProcessId=1; CreationDate=$now; ExecutablePath=$script:task.Actions[0].Execute; CommandLine=('"' + $script:task.Actions[0].Execute + '" ' + $script:task.Actions[0].Arguments)},
        [pscustomobject]@{ProcessId=41002; ParentProcessId=41001; CreationDate=$now; ExecutablePath='C:\Python\python.exe'; CommandLine='python stella_agent.py'}
    )
    $script:delay = $true; $script:polls = 0
    Stop-StellaResidentTask $script:task $target -TimeoutSeconds 3
    Assert ($script:polls -ge 4) 'Ready task is not enough: wait for captured child process exit'
    Assert ($script:stops.Count -eq 1) 'exact task stopped once; no global process kills'
    Write-Output 'PASS: task Ready still waits for process tree exit'
    # A still-Running scheduler state independently blocks replacement.
    $script:processes = @(); $script:delay = $false; $script:polls = 0
    $script:holdState = $true; $script:task = New-FixtureTask
    Stop-StellaResidentTask $script:task $target -TimeoutSeconds 3
    Assert ($script:polls -ge 4) 'must wait for non-Running state even without visible child processes'
    $script:holdState = $false
    # Unrelated PowerShell/Python commands are never treated as owned roots.
    $script:task = New-FixtureTask; $script:polls = 0
    $script:processes = @([pscustomobject]@{ProcessId=41999; ParentProcessId=1; CreationDate=$now; ExecutablePath=$script:task.Actions[0].Execute; CommandLine=('"' + $script:task.Actions[0].Execute + '" -Command Write-Output ' + $script:task.Actions[0].Arguments)})
    Stop-StellaResidentTask $script:task $target -TimeoutSeconds 1
    Assert ($script:polls -eq 2) 'unrelated process with script substring must not block or be killed'
    $script:processes = @(
        [pscustomobject]@{ProcessId=41001; ParentProcessId=1; CreationDate=$now; ExecutablePath=$script:task.Actions[0].Execute; CommandLine=('"' + $script:task.Actions[0].Execute + '" ' + $script:task.Actions[0].Arguments)},
        [pscustomobject]@{ProcessId=41002; ParentProcessId=41001; CreationDate=$now; ExecutablePath='C:\Python\python.exe'; CommandLine='python stella_agent.py'}
    )
    Write-Output 'PASS: scheduler Running gate and anchored ownership ignore unrelated processes'
    $fixture = Join-Path $root 'source'
    New-Item -ItemType Directory $fixture | Out-Null
    [IO.File]::WriteAllText((Join-Path $fixture 'stella_agent.py'), 'pass')
    Copy-Item (Join-Path $AgentDir 'run-agent.ps1') $fixture
    Copy-Item (Join-Path $AgentDir 'hardware-sensors.ps1') $fixture
    Copy-Item $LibraryZip $fixture
    $existing = Join-Path $target 'stella_agent.py'
    [IO.File]::WriteAllText($existing, '# old agent')
    function Test-StellaAdministrator { return $true }
    function Invoke-WebRequest { param($Uri, $Headers, $MaximumRedirection, [switch]$UseBasicParsing, $ErrorAction)
        Assert ($Uri -eq 'https://stella.invalid/agent/config') 'reinstall must not download or probe any other URL'
        return [pscustomobject]@{StatusCode=200}
    }
    function Export-ScheduledTask { param($TaskName, $TaskPath, $ErrorAction) return '<fixture-original-task/>' }
    $script:registers = @(); $script:failRegistration = $false
    function Register-ScheduledTask { param($TaskName, $TaskPath, $Xml, [switch]$Force, $ErrorAction) $script:registers += $TaskName; return $script:task }
    function Unregister-ScheduledTask { param($TaskName, $TaskPath, $Confirm, $ErrorAction)
        Assert ($TaskName -eq 'StellaHardwareSensors' -and $TaskPath -eq '\') 'remove only newly created fixture sensor task'
        $script:sensorTask = $null
    }
    function Register-StellaResidentTask { param($Name, $Script, $Directory, $ExtraArguments)
        if ($Name -eq 'StellaHardwareSensors') { $script:sensorTask = New-FixtureTask $Name }
        if ($script:failRegistration -and $Name -eq 'StellaAgent') { $script:failRegistration = $false; throw 'fixture replacement failure' }
        $script:registers += $Name
    }
    foreach ($name in @('Get-ScheduledTask','Stop-ScheduledTask','Start-ScheduledTask','Export-ScheduledTask','Register-ScheduledTask','Unregister-ScheduledTask','Get-CimInstance','Invoke-WebRequest')) {
        Assert ((Get-Command $name).CommandType -eq 'Function') "fixture safety mock intact: $name"
    }
    $python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
    $script:task = New-FixtureTask; $script:polls = 0; $script:delay = $false
    $script:starts = @(); $script:registers = @()
    $failed = $false; $clock = [Diagnostics.Stopwatch]::StartNew()
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python -StopTimeoutSeconds 1 }
    catch { Write-Output ('Fixture failure: ' + $_.Exception.Message); $failed = $_.Exception.Message -match 'Timed out' }
    Assert $failed 'bounded stop timeout must abort the install'
    Assert ($clock.Elapsed.TotalSeconds -lt 8) 'timeout is bounded'
    Assert ((Get-Content $existing -Raw) -eq '# old agent') 'timeout must not overwrite original agent'
    Assert (-not (Test-Path (Join-Path $target 'venv'))) 'timeout must not modify runtime'
    Assert ($script:registers.Count -eq 0 -and 'StellaAgent' -in $script:starts) 'timeout restarts prior running task without replacing its definition'
    Write-Output 'PASS: bounded timeout leaves source/runtime untouched and resumes prior task'
    $script:processes = @(); $script:task = New-FixtureTask
    $lib = Join-Path $target 'LibreHardwareMonitor'
    Expand-Archive -LiteralPath $LibraryZip -DestinationPath $lib
    Copy-Item $LibraryZip $target
    $dll = Join-Path $lib 'LibreHardwareMonitorLib.dll'
    $dllHash = (Get-FileHash $dll).Hash
    $dllTime = (Get-Item $dll).LastWriteTimeUtc
    $loaderScript = Join-Path $root 'load-library.ps1'
    $ready = Join-Path $root 'loaded'
    [IO.File]::WriteAllText($loaderScript, 'param($Dll,$Ready); [Reflection.Assembly]::LoadFrom($Dll) | Out-Null; [IO.File]::WriteAllText($Ready,"loaded"); while ($true) { Start-Sleep -Milliseconds 200 }')
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $info.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $loaderScript + '" "' + $dll + '" "' + $ready + '"'
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $loader = [Diagnostics.Process]::Start($info)
    try {
        $clock = [Diagnostics.Stopwatch]::StartNew()
        while (-not (Test-Path $ready) -and $clock.Elapsed.TotalSeconds -lt 10) { Start-Sleep -Milliseconds 100 }
        Assert (Test-Path $ready) 'real isolated PowerShell must load DLL'
        $locked = $false
        try { $handle = [IO.File]::Open($dll, 'Open', 'ReadWrite', 'None'); $handle.Dispose() } catch { $locked = $true }
        Assert $locked 'loaded real DLL must be write locked for regression'
        Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python -HardwareSensors
        Assert ((Get-FileHash $dll).Hash -eq $dllHash -and (Get-Item $dll).LastWriteTimeUtc -eq $dllTime) 'same official library reused without any DLL writes'
        Assert (-not $loader.HasExited) 'unrelated DLL loader is not killed'
        Write-Output 'PASS: real loaded-DLL same-library reinstall succeeds without download, probe or DLL replacement'
    } finally { if (-not $loader.HasExited) { $loader.Kill(); $loader.WaitForExit() }; $loader.Dispose() }
    [IO.File]::WriteAllText($existing, '# rollback original agent')
    $configFile = Join-Path $target 'private-config.json'
    $oldConfig = [IO.File]::ReadAllText($configFile)
    # Force the non-reuse path; the previous directory must survive rollback intact.
    $extra = Join-Path $lib 'old-library-marker.txt'
    [IO.File]::WriteAllText($extra, 'preserve prior library')
    $oldFiles = @(Get-ChildItem $lib -Recurse -File | ForEach-Object { $_.FullName.Substring($lib.Length) + ':' + (Get-FileHash $_.FullName).Hash }) -join "`n"
    $script:task = New-FixtureTask; $script:starts = @(); $script:registers = @()
    $script:sensorTask = $null
    $script:failRegistration = $true
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'new-fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python -HardwareSensors }
    catch { $failed = $_.Exception.Message -match 'fixture replacement failure' }
    Assert $failed 'replacement failure must be propagated'
    Assert ((Get-Content $existing -Raw) -eq '# rollback original agent') 'failure restores original agent bytes'
    Assert ([IO.File]::ReadAllText($configFile) -eq $oldConfig) 'failure restores original private config'
    $restoredFiles = @(Get-ChildItem $lib -Recurse -File | ForEach-Object { $_.FullName.Substring($lib.Length) + ':' + (Get-FileHash $_.FullName).Hash }) -join "`n"
    Assert ($restoredFiles -eq $oldFiles) 'failure restores entire original library without partial deletion'
    Assert ('StellaAgent' -in $script:starts -and 'StellaAgent' -in $script:registers) 'failure restores prior task definition and running state'
    Assert ($null -eq $script:sensorTask) 'failed install removes newly registered bridge task'
    Write-Output 'PASS: replacement failure restores agent, config, complete old library and original task'
    # If recovery itself is blocked, never delete the only remaining original.
    function Move-Item { param($LiteralPath, $Destination, $ErrorAction)
        if ((Split-Path $LiteralPath -Leaf) -eq 'previous-library') { throw 'fixture blocked recovery rename' }
        Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination -ErrorAction Stop
    }
    $script:task = New-FixtureTask; $script:failRegistration = $true
    $failed = $false
    try { Invoke-StellaInstall -Url 'https://stella.invalid' -Token 'new-fixture-secret' -NoDeps -SourceDir $fixture -InstallDir $target -PythonPath $python -HardwareSensors }
    catch { $failed = $_.Exception.Message -match 'fixture replacement failure' }
    Assert $failed 'original failure survives blocked recovery'
    $retained = @(Get-ChildItem $root -Force -Directory -Filter '.stella-stage-*')
    Assert ($retained.Count -eq 1) 'blocked recovery retains exactly its private staging directory'
    $prior = Join-Path $retained[0].FullName 'previous-library'
    $priorFiles = @(Get-ChildItem $prior -Recurse -File | ForEach-Object { $_.FullName.Substring($prior.Length) + ':' + (Get-FileHash $_.FullName).Hash }) -join "`n"
    Assert ($priorFiles -eq $oldFiles) 'blocked rollback preserves every original library byte'
    Assert ((Get-Acl $retained[0].FullName).AreAccessRulesProtected) 'retained secret backups are private'
    Assert ((Get-Content (Join-Path $retained[0].FullName 'previous-files\stella_agent.py') -Raw) -eq '# rollback original agent') 'original agent backup is retained'
    Write-Output 'PASS: blocked recovery retains private original-library/config/source backups'
} finally {
    Remove-Item $root -Recurse -Force
    $after = @(ScheduledTasks\Get-ScheduledTask | Where-Object TaskName -in @('StellaAgent','StellaHardwareSensors') | ForEach-Object { ScheduledTasks\Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath }) -join "`n"
    Assert ($before -eq $after) 'real scheduled task definitions unchanged'
    Write-Output 'PASS: real scheduled task definitions unchanged'
}
