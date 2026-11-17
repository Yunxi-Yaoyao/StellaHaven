# Run from an elevated PowerShell session. Dot-source only defines functions.
# Local mode (no Stella script downloads): set STELLA_TOKEN in this session,
# then & .\install.ps1 -Url https://<stella> -SourceDir C:\stella-source -Deps
# SourceDir contains stella_agent.py + run-agent.ps1; -HardwareSensors also
# requires hardware-sensors.ps1. Put the pinned LibreHardwareMonitor.zip there
# to avoid GitHub downloads (an existing verified install ZIP can be reused).
# -Deps: install httpx+psutil in a private venv without prompting. Default asks.
# -NoDeps: private venv without dependency installation (reduced metrics).
# URL/token are ALWAYS verified against /agent/identity, even in local source mode.
# Prefer env input over powershell.exe -File ... -Token (installer argv/history).
# No changes are made to driver security policies and no sensor GUI is opened.
# Reinstall: -StopTimeoutSeconds (1..300, default 30) waits for exact tasks and
# captured process trees before resident writes. Identical official library
# content is reused; failed replacements restore source/config/task definitions.
# If recovery is blocked, the warning names a private retained backup directory.
param(
    [string]$Url = 'http://127.0.0.1:12031',
    [string]$Token = $env:STELLA_TOKEN,
    [switch]$Deps,
    [switch]$NoDeps,
    [string]$SourceDir,
    [string]$InstallDir, [string]$Instance = '',
    [string]$PythonPath,
    [switch]$HardwareSensors,
    [ValidateRange(1,300)][int]$StopTimeoutSeconds = 30
)
function Get-StellaInstallationBinding([string]$Url, [string]$Token, [string]$Instance = '') {
    try {
        $response = Invoke-WebRequest -Uri "$Url/agent/identity" -Headers @{ Authorization = "Bearer $Token" } -MaximumRedirection 0 -UseBasicParsing -ErrorAction Stop
        if ([int]$response.StatusCode -ne 200) { throw 'Not HTTP 200' }
        $identity = $response.Content | ConvertFrom-Json
        $fields = @($identity.PSObject.Properties.Name | Sort-Object)
        if (($fields -join ',') -ne 'center_id,node_id,source_sha256,source_size,source_version' -or
            $identity.center_id -cnotmatch '^[a-f0-9]{64}$' -or $identity.source_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $identity.node_id -isnot [int] -or $identity.node_id -le 0 -or $identity.source_size -isnot [int] -or
            $identity.source_size -le 0 -or $identity.source_size -gt 8388608 -or $identity.source_version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid identity' }
        if ($Instance -and $Instance -cnotmatch '^[a-z0-9][a-z0-9-]{0,31}$') { throw 'Invalid instance label' }
        $seed = 'stella-instance-v1:' + $identity.center_id
        if ($Instance) { $seed += ':slot:' + $Instance }
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $id = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($seed)))).Replace('-','').ToLowerInvariant().Substring(0,24) }
        finally { $sha.Dispose() }
        return [pscustomobject]@{ format=1; center_id=$identity.center_id; node_id=$identity.node_id; instance_id=$id; service=('StellaAgent-' + $id); slot=$Instance; source=$identity }
    } catch { throw 'URL/token/center identity validation failed; installation aborted before resident writes.' }
}
function Assert-StellaInstanceDirectory([string]$Directory, $Binding) {
    $path = [IO.Path]::GetFullPath($Directory)
    if ($path.TrimEnd('\') -ieq 'C:\stella-agent' -or $path.StartsWith('C:\stella-agent\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Legacy installation is not adopted or overwritten.' }
    $current = $path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse installation path refused.' }
        }
        $parent = [IO.Path]::GetDirectoryName($current.TrimEnd('\'))
        if ($parent -eq $current) { break }; $current = $parent
    }
    if (Test-Path -LiteralPath $path) {
        $manifest = Join-Path $path 'instance.json'
        if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { throw 'Existing target has unknown ownership; refusing takeover.' }
        foreach ($protected in @($path, $manifest, (Join-Path $path 'private-config.json'))) {
            $acl = Get-Acl -LiteralPath $protected -ErrorAction Stop
            $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
            if (-not $acl.AreAccessRulesProtected -or $owner -notin @('S-1-5-18','S-1-5-32-544')) { throw 'Existing instance ACL is not installer-owned.' }
            foreach ($rule in $acl.Access) {
                if ($rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin @('S-1-5-18','S-1-5-32-544')) { throw 'Existing private instance permits another principal.' }
            }
        }
        $old = [IO.File]::ReadAllText($manifest) | ConvertFrom-Json
        if ((@($old.PSObject.Properties.Name | Sort-Object) -join ',') -ne 'center_id,format,instance_id,node_id,service,slot' -or
            $old.format -ne 1 -or $old.center_id -cne $Binding.center_id -or $old.node_id -ne $Binding.node_id -or
            $old.instance_id -cne $Binding.instance_id -or $old.service -cne $Binding.service -or $old.slot -cne $Binding.slot) { throw 'Instance binding mismatch; choose an explicit separate -Instance label, never replace a node silently.' }
        foreach ($file in @('instance.json','private-config.json')) {
            $item = Get-Item -LiteralPath (Join-Path $path $file) -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse configuration refused.' }
        }
    }
}
function Get-StellaPathLockName([string]$Directory) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $canonical = [IO.Path]::GetFullPath($Directory).TrimEnd('\').ToUpperInvariant()
        return 'Global\StellaInstallPath-' + ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical)))).Replace('-','').ToLowerInvariant().Substring(0,24)
    } finally { $sha.Dispose() }
}
function Resolve-StellaPython([string]$PythonPath) {
    if (-not $PythonPath) {
        $command = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { throw 'Python not found; install Python or supply -PythonPath with its absolute executable path.' }
        $PythonPath = $command.Source
    }
    if (-not [IO.Path]::IsPathRooted($PythonPath) -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'PythonPath must be an existing absolute executable path.' }
    $resolved = & $PythonPath -c 'import os,sys; print(os.path.abspath(sys.executable))' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $resolved -or -not (Test-Path -LiteralPath ([string]$resolved) -PathType Leaf)) { throw 'Unable to execute Python.' }
    return [IO.Path]::GetFullPath([string]$resolved)
}
function Get-StellaSource([string]$Name, [string]$Endpoint, [string]$Stage, [string]$SourceDir, [string]$Url) {
    $target = Join-Path $Stage $Name
    if ($SourceDir) {
        $source = Join-Path $SourceDir $Name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing trusted local source: $Name" }
        Copy-Item -LiteralPath $source -Destination $target -Force
    } else {
        try {
            $response = Invoke-WebRequest -Uri "$Url/agent/$Endpoint" -OutFile $target -PassThru -MaximumRedirection 0 -UseBasicParsing -ErrorAction Stop
            if ([int]$response.StatusCode -ne 200) { throw 'Not HTTP 200' }
        } catch { throw "Unable to download $Name; installation aborted." }
    }
    if (-not (Test-Path -LiteralPath $target) -or (Get-Item -LiteralPath $target).Length -eq 0) { throw "Empty source: $Name" }
    return $target
}
function Test-StellaPowerShell([string]$Path) {
    $tokens = $null
    $errors = $null
    [Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw 'PowerShell source syntax validation failed.' }
}
function Test-StellaAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Set-StellaPrivateAcl([string]$Path) {
    $system = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')
    $admins = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
    if ((Get-Item -LiteralPath $Path).PSIsContainer) {
        $acl = New-Object Security.AccessControl.DirectorySecurity
        $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    } else {
        $acl = New-Object Security.AccessControl.FileSecurity
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($admins)
    foreach ($sid in @($system, $admins)) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', $inheritance, 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $acl -ErrorAction Stop
}
function Confirm-StellaDependencies([switch]$Deps, [switch]$NoDeps) {
    if ($NoDeps) { return $false }
    if ($Deps) { return $true }
    $answer = Read-Host 'Install httpx/psutil in the private agent venv? [Y/n]'
    return ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim() -match '^[Yy]')
}
function Initialize-StellaRuntime([string]$Python, [string]$Directory, [switch]$NoDeps) {
    $venv = Join-Path $Directory 'venv'
    $runtime = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $runtime -PathType Leaf)) {
        & $Python -m venv --without-pip $venv
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create isolated Python venv; installation aborted.' }
    }
    $runtime = Resolve-StellaPython $runtime
    if (-not $NoDeps) {
        & $runtime -m ensurepip --upgrade | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to bootstrap pip in isolated venv.' }
        & $runtime -m pip --disable-pip-version-check install --quiet httpx psutil
        if ($LASTEXITCODE -ne 0) { throw 'Failed to install agent dependencies in isolated venv; installation aborted.' }
        & $runtime -c 'import httpx,psutil'
        if ($LASTEXITCODE -ne 0) { throw 'Agent dependency import check failed.' }
    }
    return $runtime
}
function Get-StellaHardware([string]$Stage, [string]$SourceDir, [string]$Url, [string]$InstallDir) {
    $bridge = Get-StellaSource 'hardware-sensors.ps1' 'hardware-sensors.ps1' $Stage $SourceDir $Url
    Test-StellaPowerShell $bridge
    $archive = Join-Path $Stage 'LibreHardwareMonitor.zip'
    $localArchive = $null
    if ($SourceDir -and (Test-Path -LiteralPath (Join-Path $SourceDir 'LibreHardwareMonitor.zip') -PathType Leaf)) {
        $localArchive = Join-Path $SourceDir 'LibreHardwareMonitor.zip'
    } elseif (Test-Path -LiteralPath (Join-Path $InstallDir 'LibreHardwareMonitor.zip') -PathType Leaf) {
        $localArchive = Join-Path $InstallDir 'LibreHardwareMonitor.zip'
    }
    if ($localArchive) { Copy-Item -LiteralPath $localArchive -Destination $archive -Force }
    else {
        # Only the explicitly opted-in installer downloads this official release.
        $release = 'https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v0.9.6/LibreHardwareMonitor.zip'
        try {
            $download = Invoke-WebRequest -Uri $release -OutFile $archive -PassThru -UseBasicParsing -ErrorAction Stop
            if ([int]$download.StatusCode -ne 200) { throw 'Not HTTP 200' }
        } catch { throw 'Official LibreHardwareMonitor v0.9.6 download failed. Supply LibreHardwareMonitor.zip in SourceDir.' }
    }
    $expected = '086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001'
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'LibreHardwareMonitor SHA256 mismatch; installation aborted.' }
    $library = Join-Path $Stage 'LibreHardwareMonitor'
    Expand-Archive -LiteralPath $archive -DestinationPath $library -Force
    if (-not (Test-Path -LiteralPath (Join-Path $library 'LibreHardwareMonitorLib.dll') -PathType Leaf)) { throw 'Official library DLL missing from release.' }
    return @($bridge, $archive, $library)
}
function Test-StellaLibraryContent([string]$Installed, [string]$VerifiedStage) {
    if (-not (Test-Path -LiteralPath $Installed -PathType Container)) { return $false }
    $items = @(Get-Item -LiteralPath $Installed)
    $items += @(Get-ChildItem -LiteralPath $Installed -Recurse -Force)
    if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0) { throw 'Library directory contains reparse points; installation aborted.' }
    $expectedFiles = @(Get-ChildItem -LiteralPath $VerifiedStage -Recurse -Force -File)
    $actualFiles = @(Get-ChildItem -LiteralPath $Installed -Recurse -Force -File)
    if ($expectedFiles.Count -ne $actualFiles.Count) { return $false }
    foreach ($file in $expectedFiles) {
        $relative = $file.FullName.Substring($VerifiedStage.TrimEnd('\').Length).TrimStart('\')
        $actual = Join-Path $Installed $relative
        if (-not (Test-Path -LiteralPath $actual -PathType Leaf) -or (Get-FileHash -LiteralPath $actual -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash) { return $false }
    }
    return $true
}
function Assert-StellaResidentTask($Task, [string]$Directory) {
    # Never take ownership of a same-named foreign/subfolder task.
    $scripts = @{ StellaAgent='run-agent.ps1'; StellaHardwareSensors='hardware-sensors.ps1' }
    $taskKind = [string]$Task.TaskName
    if ($taskKind -match '^(StellaAgent|StellaHardwareSensors)-([a-f0-9]{24})$') {
        $taskKind = $Matches[1]; $taskId = $Matches[2]
        $manifest = [IO.File]::ReadAllText((Join-Path $Directory 'instance.json')) | ConvertFrom-Json
        if ($manifest.instance_id -cne $taskId -or $manifest.service -cne ('StellaAgent-' + $taskId)) { throw 'Task does not belong to this instance.' }
    } elseif ($Directory.TrimEnd('\') -ine 'C:\stella-agent') { throw 'Unscoped legacy task cannot own an instance directory.' }
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ($Task.TaskPath -ne '\' -or -not $scripts.ContainsKey($taskKind) -or @($Task.Actions).Count -ne 1 -or $Task.Principal.UserId -notin @('SYSTEM','S-1-5-18')) {
        throw 'Existing task is not a verified root SYSTEM Stella task; installation aborted.'
    }
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $Directory $scripts[$taskKind]) + '"'
    if ($taskKind -eq 'StellaHardwareSensors') { $arguments += ' -IntervalSeconds 30' }
    $action = $Task.Actions[0]
    if ($action.Execute -ne $powershell -or $action.Arguments -ne $arguments -or $action.WorkingDirectory -ne $Directory) {
        throw 'Existing Stella task action does not match this install directory; installation aborted.'
    }
}
function Stop-StellaResidentTask($Task, [string]$Directory, [ValidateRange(1,300)][int]$TimeoutSeconds = 30) {
    Assert-StellaResidentTask $Task $Directory
    $action = $Task.Actions[0]
    $tracked = @{}
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $stopped = $false
    do {
        $processes = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
        foreach ($process in $processes) {
            # Anchor the full command; a substring of a foreign PowerShell is not ownership.
            $executable = '"?' + [regex]::Escape($action.Execute) + '"?'
            if ($process.ExecutablePath -eq $action.Execute -and $process.CommandLine -match ('^' + $executable + '\s+' + [regex]::Escape($action.Arguments) + '\s*$')) {
                $tracked[[string]$process.ProcessId] = $process.CreationDate
            }
        }
        do {
            $added = $false
            foreach ($process in $processes) {
                $id = [string]$process.ProcessId
                $parent = [string]$process.ParentProcessId
                if (-not $tracked.ContainsKey($id) -and $tracked.ContainsKey($parent) -and $process.CreationDate -ge $tracked[$parent]) {
                    $tracked[$id] = $process.CreationDate
                    $added = $true
                }
            }
        } while ($added)
        if (-not $stopped) {
            Stop-ScheduledTask -TaskName $Task.TaskName -TaskPath '\' -ErrorAction Stop
            $stopped = $true
            # Always poll again after Stop, which is asynchronous.
        } else {
            $current = Get-ScheduledTask -TaskName $Task.TaskName -TaskPath '\' -ErrorAction Stop
            Assert-StellaResidentTask $current $Directory
            $alive = @($processes | Where-Object { $tracked.ContainsKey([string]$_.ProcessId) -and $_.CreationDate -eq $tracked[[string]$_.ProcessId] })
            if ($current.State -ne 'Running' -and $alive.Count -eq 0) { return }
        }
        if ($clock.Elapsed.TotalSeconds -ge $TimeoutSeconds) { throw "Timed out waiting for exact $($Task.TaskName) task/process tree; installed files were not replaced." }
        Start-Sleep -Milliseconds 100
    } while ($true)
}
function Register-StellaResidentTask([string]$Name, [string]$Script, [string]$Directory, [string]$ExtraArguments = '') {
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $Script + '"' + $ExtraArguments
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $Directory
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -TaskPath '\' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $Name -TaskPath '\' -ErrorAction Stop
    if ($task.Principal.UserId -notin @('SYSTEM', 'S-1-5-18') -or $task.Actions[0].Execute -ne $powershell -or $task.Actions[0].Arguments -ne $arguments -or $task.Settings.ExecutionTimeLimit -ne 'PT0S') {
        throw 'Scheduled task readback does not match requested configuration; not starting.'
    }
    Start-ScheduledTask -TaskName $Name -TaskPath '\' -ErrorAction Stop
}
function Write-StellaInstanceFiles([string]$Directory, $Binding) {
    $manifestPath = Join-Path $Directory 'instance.json'
    $manifest = @{ format=1; center_id=$Binding.center_id; node_id=$Binding.node_id; instance_id=$Binding.instance_id; service=$Binding.service; slot=$Binding.slot }
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
    Set-StellaPrivateAcl $manifestPath
    # All paths/task names are installer constants, never server command payloads.
    $safeDirectory = $Directory.Replace("'", "''")
    $pathLockName = Get-StellaPathLockName $Directory
    $header = "param([switch]`$Run)`r`n`$Directory = '$safeDirectory'`r`n`$Id = '$($Binding.instance_id)'`r`n`$Center = '$($Binding.center_id)'`r`n`$Node = $($Binding.node_id)`r`n`$PathLockName = '$pathLockName'`r`n"
    $body = @'
$ErrorActionPreference = 'Stop'
$manifest = [IO.File]::ReadAllText((Join-Path $Directory 'instance.json')) | ConvertFrom-Json
if ($manifest.instance_id -cne $Id -or $manifest.center_id -cne $Center -or $manifest.node_id -ne $Node -or
    $manifest.service -cne ('StellaAgent-' + $Id) -or ([IO.Path]::GetFullPath($PSScriptRoot) -ine $Directory)) { throw 'Removal ownership mismatch.' }
$mutex = New-Object Threading.Mutex($false, ('Global\StellaInstall-' + $Id))
$held = $false; $pathHeld = $false
$pathMutex = New-Object Threading.Mutex($false, $PathLockName)
if ($Run) { Start-Sleep -Seconds 3 } # preserve the agent's result-report window
try {
    $held = $mutex.WaitOne(0)
    if (-not $held) { throw 'Installer/removal already owns instance.' }
    $pathHeld = $pathMutex.WaitOne(0)
    if (-not $pathHeld) { throw 'Another installer owns removal path.' }
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $removeTask = 'StellaRemove-' + $Id
    $selfArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $Directory 'uninstall-instance.ps1') + '" -Run'
    function Assert-ExactTask($Task, [string]$Script, [string]$Extra = '') {
        $expected = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $Directory $Script) + '"' + $Extra
        if ($Task.TaskPath -ne '\' -or @($Task.Actions).Count -ne 1 -or $Task.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or
            $Task.Actions[0].Execute -ine $powershell -or $Task.Actions[0].Arguments -cne $expected -or $Task.Actions[0].WorkingDirectory -ine $Directory) { throw 'Foreign task; removal refused.' }
    }
    $tasks = @()
    foreach ($kind in @('StellaAgent','StellaHardwareSensors')) {
        $task = Get-ScheduledTask -TaskName ($kind + '-' + $Id) -TaskPath '\' -ErrorAction SilentlyContinue
        if ($task) {
            if ($kind -eq 'StellaAgent') { Assert-ExactTask $task 'run-agent.ps1' }
            else { Assert-ExactTask $task 'hardware-sensors.ps1' ' -IntervalSeconds 30' }
            $tasks += $task
        }
    }
    if (-not $Run) {
        if (Get-ScheduledTask -TaskName $removeTask -TaskPath '\' -ErrorAction SilentlyContinue) { throw 'Removal task already exists; refusing overwrite.' }
        $action = New-ScheduledTaskAction -Execute $powershell -Argument $selfArguments -WorkingDirectory $Directory
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $removeTask -TaskPath '\' -Action $action -Principal $principal | Out-Null
        $readback = Get-ScheduledTask -TaskName $removeTask -TaskPath '\' -ErrorAction Stop
        Assert-ExactTask $readback 'uninstall-instance.ps1' ' -Run'
        $pathMutex.ReleaseMutex(); $pathHeld = $false
        $mutex.ReleaseMutex(); $held = $false
        Start-ScheduledTask -TaskName $removeTask -TaskPath '\' -ErrorAction Stop
        return
    }
    $self = Get-ScheduledTask -TaskName $removeTask -TaskPath '\' -ErrorAction Stop
    Assert-ExactTask $self 'uninstall-instance.ps1' ' -Run'
    foreach ($task in $tasks) {
        Stop-ScheduledTask -TaskName $task.TaskName -TaskPath '\' -ErrorAction Stop
        $clock = [Diagnostics.Stopwatch]::StartNew()
        do {
            $current = Get-ScheduledTask -TaskName $task.TaskName -TaskPath '\' -ErrorAction Stop
            if ($current.State -ne 'Running') { break }
            if ($clock.Elapsed.TotalSeconds -gt 30) { throw 'Instance task did not stop.' }
            Start-Sleep -Milliseconds 100
        } while ($true)
        Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath '\' -Confirm:$false -ErrorAction Stop
        if (Get-ScheduledTask -TaskName $task.TaskName -TaskPath '\' -ErrorAction SilentlyContinue) { throw 'Task removal readback failed.' }
    }
    # Reparse roots cannot redirect deletion into legacy/another center.
    if ((Get-Item -LiteralPath $Directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse removal refused.' }
    $pending = New-Object 'Collections.Generic.Queue[string]'
    $pending.Enqueue($Directory)
    while ($pending.Count) {
        foreach ($item in @(Get-ChildItem -LiteralPath $pending.Dequeue() -Force)) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse descendant removal refused.' }
            if ($item.PSIsContainer) { $pending.Enqueue($item.FullName) }
        }
    }
    Remove-Item -LiteralPath $Directory -Recurse -Force
    Unregister-ScheduledTask -TaskName $removeTask -TaskPath '\' -Confirm:$false -ErrorAction Stop
} finally {
    if ($pathHeld) { $pathMutex.ReleaseMutex() }; $pathMutex.Dispose()
    if ($held) { $mutex.ReleaseMutex() }; $mutex.Dispose()
}
'@
    $uninstallPath = Join-Path $Directory 'uninstall-instance.ps1'
    [IO.File]::WriteAllText($uninstallPath, $header + $body, (New-Object Text.UTF8Encoding($false)))
    Set-StellaPrivateAcl $uninstallPath
    Test-StellaPowerShell $uninstallPath
}
function Invoke-StellaInstall {
    [CmdletBinding()]
    param(
        [string]$Url, [string]$Token = $env:STELLA_TOKEN, [switch]$Deps, [switch]$NoDeps,
        [string]$SourceDir, [string]$InstallDir, [string]$Instance = '',
        [string]$PythonPath, [switch]$HardwareSensors,
        [ValidateRange(1,300)][int]$StopTimeoutSeconds = 30
    )
    $ErrorActionPreference = 'Stop'
    if (-not (Test-StellaAdministrator)) { throw 'Run the installer in an elevated Administrator PowerShell session.' }
    if ($Deps -and $NoDeps) { throw 'Choose either -Deps or -NoDeps, not both.' }
    if (-not $Url) { $Url = 'http://127.0.0.1:12031' }
    $uri = $null
    if (-not [Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('https', 'http') -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { throw 'Url must be an HTTP(S) base URL without credentials, query or fragment.' }
    if ($InstallDir -and $InstallDir.Contains('"')) { throw 'InstallDir cannot contain quotes.' }
    if ([string]::IsNullOrWhiteSpace($Token)) { throw 'Missing token; set STELLA_TOKEN in this PowerShell session.' }
    $Url = $Url.TrimEnd('/')
    $binding = Get-StellaInstallationBinding $Url $Token $Instance
    if (-not $InstallDir) { $InstallDir = Join-Path 'C:\stella-agents' $binding.instance_id }
    $InstallDir = [IO.Path]::GetFullPath($InstallDir)
    Assert-StellaInstanceDirectory $InstallDir $binding
    $agentTask = 'StellaAgent-' + $binding.instance_id
    $sensorTask = 'StellaHardwareSensors-' + $binding.instance_id
    $hadDirectory = Test-Path -LiteralPath $InstallDir
    $python = Resolve-StellaPython $PythonPath
    $stage = Join-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($InstallDir))) ('.stella-stage-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Set-StellaPrivateAcl $stage
    $retainStage = $false
    $oldTasks = @(); $stoppedTasks = @(); $backups = @(); $registeredNames = @()
    $libraryMoved = $false; $libraryInstalled = $false; $writesStarted = $false
    $libraryDestination = Join-Path $InstallDir 'LibreHardwareMonitor'
    $libraryBackup = Join-Path $stage 'previous-library'
    $mutex = New-Object Threading.Mutex($false, ('Global\StellaInstall-' + $binding.instance_id))
    $lockAcquired = $false; $pathLockAcquired = $false
    $pathMutex = New-Object Threading.Mutex($false, (Get-StellaPathLockName $InstallDir))
    try {
        $lockAcquired = $mutex.WaitOne(0)
        if (-not $lockAcquired) { throw 'Another installer/removal owns this instance.' }
        $pathLockAcquired = $pathMutex.WaitOne(0)
        if (-not $pathLockAcquired) { throw 'Another instance installer owns this target directory.' }
        Assert-StellaInstanceDirectory $InstallDir $binding
        # A trusted same-center alias may repair sources/tasks, not migrate the
        # installed reporting origin (the authenticated channel cache binds it).
        $reportUrl = $Url
        if (Test-Path -LiteralPath $InstallDir) {
            $installedConfig = [IO.File]::ReadAllText((Join-Path $InstallDir 'private-config.json')) | ConvertFrom-Json
            if ([string]::IsNullOrWhiteSpace([string]$installedConfig.STELLA_URL)) { throw 'Existing installed reporting URL is missing.' }
            $reportUrl = [string]$installedConfig.STELLA_URL
        }
        $agent = Get-StellaSource 'stella_agent.py' 'script' $stage $SourceDir $Url
        $wrapper = Get-StellaSource 'run-agent.ps1' 'run-agent.ps1' $stage $SourceDir $Url
        & $python -c "import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_bytes(), sys.argv[1], 'exec')" $agent 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'Python source syntax validation failed.' }
        Test-StellaPowerShell $wrapper
        if ((Get-Item -LiteralPath $agent).Length -ne $binding.source.source_size -or
            (Get-FileHash -LiteralPath $agent -Algorithm SHA256).Hash.ToLowerInvariant() -cne $binding.source.source_sha256) { throw 'Agent source SHA256/size mismatch; installed files were not changed.' }
        $hardwareFiles = @()
        $reuseLibrary = $false
        if ($HardwareSensors) {
            $hardwareFiles = @(Get-StellaHardware $stage $SourceDir $Url $InstallDir)
            # Trust only content matched file-for-file against the SHA-pinned ZIP.
            $reuseLibrary = Test-StellaLibraryContent (Join-Path $InstallDir 'LibreHardwareMonitor') $hardwareFiles[2]
        }
        $replaceTasks = @($agentTask)
        if ($HardwareSensors) { $replaceTasks += $sensorTask }
        $oldTasks = @()
        foreach ($name in $replaceTasks) {
            $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
            if ($task) {
                Assert-StellaResidentTask $task $InstallDir
                $xml = Export-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction Stop
                $oldTasks += [pscustomobject]@{ Task=$task; Running=($task.State -eq 'Running'); Xml=$xml }
            }
        }
        # Back up all replaceable files into the already private staging directory.
        $files = @($agent, $wrapper) + @($hardwareFiles | Where-Object { -not (Get-Item -LiteralPath $_).PSIsContainer })
        $destinations = @($files | ForEach-Object { Join-Path $InstallDir ([IO.Path]::GetFileName($_)) })
        $destinations += Join-Path $InstallDir 'private-config.json'
        $destinations += Join-Path $InstallDir 'instance.json'
        $destinations += Join-Path $InstallDir 'uninstall-instance.ps1'
        $backupDir = Join-Path $stage 'previous-files'
        New-Item -ItemType Directory -Path $backupDir | Out-Null
        foreach ($destination in $destinations) {
            $saved = Join-Path $backupDir ([IO.Path]::GetFileName($destination))
            $exists = Test-Path -LiteralPath $destination -PathType Leaf
            if ($exists) { Copy-Item -LiteralPath $destination -Destination $saved -Force }
            $backups += [pscustomobject]@{ Destination=$destination; Saved=$saved; Existed=$exists }
        }
        foreach ($old in $oldTasks) {
            $stoppedTasks += $old
            Stop-StellaResidentTask $old.Task $InstallDir -TimeoutSeconds $StopTimeoutSeconds
        }
        $writesStarted = $true
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        Set-StellaPrivateAcl $InstallDir
        $installDependencies = Confirm-StellaDependencies -Deps:$Deps -NoDeps:$NoDeps
        $python = Initialize-StellaRuntime $python $InstallDir -NoDeps:(-not $installDependencies)
        foreach ($source in (@($agent, $wrapper) + $hardwareFiles)) {
            $destination = Join-Path $InstallDir ([IO.Path]::GetFileName($source))
            if ((Get-Item -LiteralPath $source).PSIsContainer) {
                if ($reuseLibrary) { continue }
                # Rename, never delete a prior library before the replacement succeeds.
                if (Test-Path -LiteralPath $destination) {
                    Move-Item -LiteralPath $destination -Destination $libraryBackup
                    $libraryMoved = $true
                }
                Move-Item -LiteralPath $source -Destination $destination
                $libraryInstalled = $true
            } else { Copy-Item -LiteralPath $source -Destination $destination -Force }
            Set-StellaPrivateAcl $destination
        }
        $configPath = Join-Path $InstallDir 'private-config.json'
        # Create/lock the file BEFORE writing any secret, including on upgrade.
        if (-not (Test-Path -LiteralPath $configPath)) { New-Item -ItemType File -Path $configPath | Out-Null }
        Set-StellaPrivateAcl $configPath
        $config = @{ STELLA_URL=$reportUrl; STELLA_TOKEN=$Token; PythonPath=$python; STELLA_HARDWARE_SENSORS_FILE=(Join-Path $InstallDir 'hardware-sensors.json'); STELLA_INSTANCE_ID=$binding.instance_id; STELLA_INSTANCE_MANIFEST=(Join-Path $InstallDir 'instance.json') }
        [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
        Write-StellaInstanceFiles $InstallDir $binding
        if ($HardwareSensors) {
            $registeredNames += $sensorTask
            Register-StellaResidentTask $sensorTask (Join-Path $InstallDir 'hardware-sensors.ps1') $InstallDir ' -IntervalSeconds 30'
        }
        $registeredNames += $agentTask
        Register-StellaResidentTask $agentTask (Join-Path $InstallDir 'run-agent.ps1') $InstallDir
        Write-Host 'StellaAgent installed. Startup/restart task registered and start requested; verify reporting in Stella.'
    } catch {
        $installationError = $_
        try {
            if ($writesStarted) {
                # A newly started bridge may have loaded the replacement DLL already.
                foreach ($name in $registeredNames) {
                    $current = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
                    if ($current) { Stop-StellaResidentTask $current $InstallDir -TimeoutSeconds $StopTimeoutSeconds }
                }
                if ($libraryInstalled) { Move-Item -LiteralPath $libraryDestination -Destination (Join-Path $stage 'rejected-library') }
                if ($libraryMoved) { Move-Item -LiteralPath $libraryBackup -Destination $libraryDestination }
                foreach ($backup in $backups) {
                    if ($backup.Existed) {
                        Copy-Item -LiteralPath $backup.Saved -Destination $backup.Destination -Force
                        Set-StellaPrivateAcl $backup.Destination
                        if ((Get-FileHash -LiteralPath $backup.Destination).Hash -ne (Get-FileHash -LiteralPath $backup.Saved).Hash) { throw 'Restored file readback failed.' }
                    } elseif (Test-Path -LiteralPath $backup.Destination) { Remove-Item -LiteralPath $backup.Destination -Force }
                }
                foreach ($name in $registeredNames) {
                    if ($name -notin @($oldTasks | ForEach-Object { $_.Task.TaskName })) {
                        if (Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue) {
                            Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false -ErrorAction Stop
                            if (Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue) { throw 'New task removal readback failed.' }
                        }
                    }
                }
                foreach ($old in $oldTasks) {
                    Register-ScheduledTask -TaskName $old.Task.TaskName -TaskPath '\' -Xml $old.Xml -Force -ErrorAction Stop | Out-Null
                    $restored = Get-ScheduledTask -TaskName $old.Task.TaskName -TaskPath '\' -ErrorAction Stop
                    Assert-StellaResidentTask $restored $InstallDir
                    $restoredXml = Export-ScheduledTask -TaskName $old.Task.TaskName -TaskPath '\' -ErrorAction Stop
                    if (([xml]$restoredXml).OuterXml -ne ([xml]$old.Xml).OuterXml) { throw 'Original task definition restoration readback failed.' }
                }
            }
            foreach ($old in $stoppedTasks) {
                if ($old.Running) { Start-ScheduledTask -TaskName $old.Task.TaskName -TaskPath '\' -ErrorAction Stop }
            }
            if ($writesStarted -and -not $hadDirectory -and (Test-Path -LiteralPath $InstallDir)) {
                if ((Get-Item -LiteralPath $InstallDir -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'New directory became a reparse point; cleanup refused.' }
                Remove-Item -LiteralPath $InstallDir -Recurse -Force
            }
        } catch {
            # Never erase the only original DLL/config backup after a failed recovery.
            $retainStage = $true
            Write-Warning "Recovery could not complete; original backups retained in private directory: $stage. No global processes were killed."
        }
        throw $installationError
    } finally {
        if ($pathLockAcquired) { $pathMutex.ReleaseMutex() }; $pathMutex.Dispose()
        if ($lockAcquired) { $mutex.ReleaseMutex() }; $mutex.Dispose()
        if (-not $retainStage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
}
if ($MyInvocation.InvocationName -ne '.') {
    Invoke-StellaInstall @PSBoundParameters
}
