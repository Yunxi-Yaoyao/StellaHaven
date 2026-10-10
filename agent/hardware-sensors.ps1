# Optional read-only LibreHardwareMonitor bridge. Run elevated/SYSTEM.
# No network listener, no credentials, and no changes to clocks or fan controls.
param(
    [string]$LibraryDir = (Join-Path $PSScriptRoot 'LibreHardwareMonitor'),
    [string]$OutputPath = (Join-Path $PSScriptRoot 'hardware-sensors.json'),
    [int]$IntervalSeconds = 30,
    [switch]$Once,
    [switch]$LibraryOnly
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function ConvertTo-HardwareSnapshot($Rows) {
    $valid = @($Rows | Where-Object {
        $null -ne $_.value -and -not [double]::IsNaN([double]$_.value) -and -not [double]::IsInfinity([double]$_.value)
    })
    $cpuTemps = @($valid | Where-Object { $_.hardware_type -eq 'Cpu' -and $_.type -eq 'Temperature' -and $_.value -ge -20 -and $_.value -le 150 })
    $temp = $cpuTemps | Where-Object { $_.name -match 'Tctl/Tdie|CPU Package' } | Select-Object -First 1
    if ($null -eq $temp) { $temp = $cpuTemps | Where-Object { $_.name -match 'Tdie|Core' } | Sort-Object value -Descending | Select-Object -First 1 }
    $clocks = @($valid | Where-Object { $_.hardware_type -eq 'Cpu' -and $_.type -eq 'Clock' -and $_.name -notmatch 'Bus|Effective' -and $_.value -gt 0 -and $_.value -lt 20000 })
    $clock = $clocks | Where-Object { $_.name -eq 'Cores (Average)' } | Select-Object -First 1
    $frequency = $null
    $frequencySource = $null
    if ($null -ne $clock) {
        $frequency = [double]$clock.value
        $frequencySource = 'LibreHardwareMonitor:' + $clock.name
    } else {
        $cores = @($clocks | Where-Object { $_.name -match '^CPU Core|^Core #' })
        if ($cores.Count -gt 0) { $frequency = [double]($cores | Measure-Object value -Average).Average; $frequencySource = 'LibreHardwareMonitor:core clocks average' }
    }
    $sensors = @($valid | Where-Object {
        ($_.type -eq 'Temperature' -and $_.value -ge -20 -and $_.value -le 150) -or
        ($_.type -eq 'Fan' -and $_.value -ge 0 -and $_.value -le 50000)
    } | Select-Object -First 64 | ForEach-Object {
        @{ name=($_.hardware + ' / ' + $_.name); kind=$(if ($_.type -eq 'Fan') { 'fan' } else { 'temperature' }); value=[math]::Round([double]$_.value, 2); unit=$(if ($_.type -eq 'Fan') { 'RPM' } else { [string][char]0x00B0 + 'C' }); source='LibreHardwareMonitor' }
    })
    return @{
        sampled_at=[datetime]::UtcNow.ToString('o')
        cpu_temperature_c=$(if ($null -ne $temp) { [math]::Round([double]$temp.value, 2) } else { $null })
        cpu_temperature_source=$(if ($null -ne $temp) { 'LibreHardwareMonitor:' + $temp.name } else { $null })
        cpu_frequency_mhz=$(if ($null -ne $frequency) { [math]::Round($frequency, 2) } else { $null })
        cpu_frequency_source=$frequencySource
        sensors=@($sensors)
    }
}
function Write-HardwareSnapshot($Snapshot, [string]$Target) {
    $temporary = $Target + '.new'
    try {
        $json = ConvertTo-Json -InputObject $Snapshot -Depth 8 -Compress
        [IO.File]::WriteAllText($temporary, $json, (New-Object Text.UTF8Encoding($false)))
        if ([IO.File]::Exists($Target)) {
            # Windows PowerShell 5.1 binds $null as an empty backup path.
            $backup = $Target + '.bak'
            try { [IO.File]::Replace($temporary, $Target, $backup) }
            finally { if ([IO.File]::Exists($backup)) { [IO.File]::Delete($backup) } }
        }
        else { [IO.File]::Move($temporary, $Target) }
    } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}
if ($LibraryOnly) { return }
if ($IntervalSeconds -lt 5 -or $IntervalSeconds -gt 300) { throw 'Interval must be 5 to 300 seconds' }
Set-Location $LibraryDir
[Reflection.Assembly]::LoadFrom((Join-Path $LibraryDir 'LibreHardwareMonitorLib.dll')) | Out-Null
$computer = New-Object LibreHardwareMonitor.Hardware.Computer
$computer.IsCpuEnabled = $true
$computer.IsMotherboardEnabled = $true
$computer.Open()
try {
    function Read-HardwareRows($Hardware) {
        $Hardware.Update()
        foreach ($sensor in $Hardware.Sensors) {
            if ([string]$sensor.SensorType -in @('Temperature','Clock','Fan')) {
                @{ hardware=[string]$Hardware.Name; hardware_type=[string]$Hardware.HardwareType; name=[string]$sensor.Name; type=[string]$sensor.SensorType; value=$sensor.Value }
            }
        }
        foreach ($child in $Hardware.SubHardware) { Read-HardwareRows $child }
    }
    do {
        $rows = @($computer.Hardware | ForEach-Object { Read-HardwareRows $_ })
        $snapshot = ConvertTo-HardwareSnapshot $rows
        Write-HardwareSnapshot $snapshot $OutputPath
        if (-not $Once) { Start-Sleep -Seconds $IntervalSeconds }
    } while (-not $Once)
} finally { $computer.Close() }
