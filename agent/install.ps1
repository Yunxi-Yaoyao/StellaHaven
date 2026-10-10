# Run from an elevated PowerShell session. Dot-source only defines functions.
# Local mode (no Stella script downloads): set STELLA_TOKEN in this session,
# then & .\install.ps1 -Url https://<stella> -SourceDir C:\stella-source -Deps
# SourceDir contains stella_agent.py + run-agent.ps1; -HardwareSensors also
# requires hardware-sensors.ps1. Put the pinned LibreHardwareMonitor.zip there
# to avoid GitHub downloads (an existing verified install ZIP can be reused).
# -Deps: install httpx+psutil in a private venv without prompting. Default asks.
# -NoDeps: private venv without dependency installation (reduced metrics).
# URL/token are ALWAYS verified against the real /agent/config, even locally.
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
    [string]$InstallDir = 'C:\stella-agent',
    [string]$PythonPath,
    [switch]$HardwareSensors,
    [ValidateRange(1,300)][int]$StopTimeoutSeconds = 30
)
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
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if ($Task.TaskPath -ne '\' -or -not $scripts.ContainsKey([string]$Task.TaskName) -or @($Task.Actions).Count -ne 1 -or $Task.Principal.UserId -notin @('SYSTEM','S-1-5-18')) {
        throw 'Existing task is not a verified root SYSTEM Stella task; installation aborted.'
    }
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $Directory $scripts[$Task.TaskName]) + '"'
    if ($Task.TaskName -eq 'StellaHardwareSensors') { $arguments += ' -IntervalSeconds 30' }
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
function Invoke-StellaInstall {
    [CmdletBinding()]
    param(
        [string]$Url, [string]$Token = $env:STELLA_TOKEN, [switch]$Deps, [switch]$NoDeps,
        [string]$SourceDir, [string]$InstallDir = 'C:\stella-agent',
        [string]$PythonPath, [switch]$HardwareSensors,
        [ValidateRange(1,300)][int]$StopTimeoutSeconds = 30
    )
    $ErrorActionPreference = 'Stop'
    if (-not (Test-StellaAdministrator)) { throw 'Run the installer in an elevated Administrator PowerShell session.' }
    if ($Deps -and $NoDeps) { throw 'Choose either -Deps or -NoDeps, not both.' }
    if (-not $Url) { $Url = 'http://127.0.0.1:12031' }
    $uri = $null
    if (-not [Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -notin @('https', 'http') -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { throw 'Url must be an HTTP(S) base URL without credentials, query or fragment.' }
    $InstallDir = [IO.Path]::GetFullPath($InstallDir)
    if ($InstallDir.Contains('"')) { throw 'InstallDir cannot contain quotes.' }
    if ([string]::IsNullOrWhiteSpace($Token)) { throw 'Missing token; set STELLA_TOKEN in this PowerShell session.' }
    $Url = $Url.TrimEnd('/')
    try {
        $response = Invoke-WebRequest -Uri "$Url/agent/config" -Headers @{ Authorization = "Bearer $Token" } -MaximumRedirection 0 -UseBasicParsing -ErrorAction Stop
        if ([int]$response.StatusCode -ne 200) { throw 'Not HTTP 200' }
    } catch { throw 'URL/token validation failed: /agent/config must return HTTP 200. Installation aborted.' }
    $python = Resolve-StellaPython $PythonPath
    $stage = Join-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($InstallDir))) ('.stella-stage-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Set-StellaPrivateAcl $stage
    $retainStage = $false
    $oldTasks = @(); $stoppedTasks = @(); $backups = @(); $registeredNames = @()
    $libraryMoved = $false; $libraryInstalled = $false; $writesStarted = $false
    $libraryDestination = Join-Path $InstallDir 'LibreHardwareMonitor'
    $libraryBackup = Join-Path $stage 'previous-library'
    try {
        $agent = Get-StellaSource 'stella_agent.py' 'script' $stage $SourceDir $Url
        $wrapper = Get-StellaSource 'run-agent.ps1' 'run-agent.ps1' $stage $SourceDir $Url
        & $python -c "import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_bytes(), sys.argv[1], 'exec')" $agent 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'Python source syntax validation failed.' }
        Test-StellaPowerShell $wrapper
        $hardwareFiles = @()
        $reuseLibrary = $false
        if ($HardwareSensors) {
            $hardwareFiles = @(Get-StellaHardware $stage $SourceDir $Url $InstallDir)
            # Trust only content matched file-for-file against the SHA-pinned ZIP.
            $reuseLibrary = Test-StellaLibraryContent (Join-Path $InstallDir 'LibreHardwareMonitor') $hardwareFiles[2]
        }
        $replaceTasks = @('StellaAgent')
        if ($HardwareSensors) { $replaceTasks += 'StellaHardwareSensors' }
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
        $config = @{ STELLA_URL=$Url; STELLA_TOKEN=$Token; PythonPath=$python; STELLA_HARDWARE_SENSORS_FILE=(Join-Path $InstallDir 'hardware-sensors.json') }
        [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
        if ($HardwareSensors) {
            $registeredNames += 'StellaHardwareSensors'
            Register-StellaResidentTask 'StellaHardwareSensors' (Join-Path $InstallDir 'hardware-sensors.ps1') $InstallDir ' -IntervalSeconds 30'
        }
        $registeredNames += 'StellaAgent'
        Register-StellaResidentTask 'StellaAgent' (Join-Path $InstallDir 'run-agent.ps1') $InstallDir
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
        } catch {
            # Never erase the only original DLL/config backup after a failed recovery.
            $retainStage = $true
            Write-Warning "Recovery could not complete; original backups retained in private directory: $stage. No global processes were killed."
        }
        throw $installationError
    } finally {
        if (-not $retainStage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
}
if ($MyInvocation.InvocationName -ne '.') {
    Invoke-StellaInstall @PSBoundParameters
}
