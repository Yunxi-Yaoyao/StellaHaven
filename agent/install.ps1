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
param(
    [string]$Url = 'http://127.0.0.1:12031',
    [string]$Token = $env:STELLA_TOKEN,
    [switch]$Deps,
    [switch]$NoDeps,
    [string]$SourceDir,
    [string]$InstallDir = 'C:\stella-agent',
    [string]$PythonPath,
    [switch]$HardwareSensors
)
function Resolve-StellaPython([string]$PythonPath) {
    if (-not $PythonPath) {
        $command = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
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
function Register-StellaResidentTask([string]$Name, [string]$Script, [string]$Directory, [string]$ExtraArguments = '') {
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $Script + '"' + $ExtraArguments
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $Directory
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    if ($task.Principal.UserId -notin @('SYSTEM', 'S-1-5-18') -or $task.Actions[0].Execute -ne $powershell -or $task.Actions[0].Arguments -ne $arguments -or $task.Settings.ExecutionTimeLimit -ne 'PT0S') {
        throw 'Scheduled task readback does not match requested configuration; not starting.'
    }
    Start-ScheduledTask -TaskName $Name -ErrorAction Stop
}
function Invoke-StellaInstall {
    [CmdletBinding()]
    param(
        [string]$Url, [string]$Token = $env:STELLA_TOKEN, [switch]$Deps, [switch]$NoDeps,
        [string]$SourceDir, [string]$InstallDir = 'C:\stella-agent',
        [string]$PythonPath, [switch]$HardwareSensors
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
    try {
        $agent = Get-StellaSource 'stella_agent.py' 'script' $stage $SourceDir $Url
        $wrapper = Get-StellaSource 'run-agent.ps1' 'run-agent.ps1' $stage $SourceDir $Url
        & $python -c "import pathlib,sys; compile(pathlib.Path(sys.argv[1]).read_bytes(), sys.argv[1], 'exec')" $agent 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'Python source syntax validation failed.' }
        Test-StellaPowerShell $wrapper
        $hardwareFiles = @()
        if ($HardwareSensors) { $hardwareFiles = @(Get-StellaHardware $stage $SourceDir $Url $InstallDir) }
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
        Set-StellaPrivateAcl $InstallDir
        $installDependencies = Confirm-StellaDependencies -Deps:$Deps -NoDeps:$NoDeps
        $python = Initialize-StellaRuntime $python $InstallDir -NoDeps:(-not $installDependencies)
        $replaceTasks = @('StellaAgent')
        if ($HardwareSensors) { $replaceTasks += 'StellaHardwareSensors' }
        foreach ($name in $replaceTasks) {
            if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
                Stop-ScheduledTask -TaskName $name -ErrorAction Stop
            }
        }
        foreach ($source in (@($agent, $wrapper) + $hardwareFiles)) {
            $destination = Join-Path $InstallDir ([IO.Path]::GetFileName($source))
            if ((Get-Item -LiteralPath $source).PSIsContainer) {
                # Replace the verified library directory, not copy it inside itself.
                if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
                Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
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
            Register-StellaResidentTask 'StellaHardwareSensors' (Join-Path $InstallDir 'hardware-sensors.ps1') $InstallDir ' -IntervalSeconds 30'
        }
        Register-StellaResidentTask 'StellaAgent' (Join-Path $InstallDir 'run-agent.ps1') $InstallDir
        Write-Host 'StellaAgent installed. Startup/restart task registered and start requested; verify reporting in Stella.'
    } finally { Remove-Item -LiteralPath $stage -Recurse -Force }
}
if ($MyInvocation.InvocationName -ne '.') {
    Invoke-StellaInstall @PSBoundParameters
}
