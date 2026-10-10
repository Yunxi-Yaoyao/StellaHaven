$ErrorActionPreference = 'Stop'
$bridge = Join-Path $PSScriptRoot '..\hardware-sensors.ps1'
if (-not (Test-Path $bridge)) { throw 'Hardware sensor bridge is not implemented' }
. $bridge -LibraryOnly
function Assert-Equal($actual, $expected, $message) {
    if ($actual -ne $expected) { throw "$message (actual=$actual expected=$expected)" }
}
$rows = @(
    @{hardware_type='SuperIO'; hardware='Board'; name='Temperature #1'; type='Temperature'; value=99},
    @{hardware_type='Cpu'; hardware='CPU'; name='CCD1 (Tdie)'; type='Temperature'; value=60},
    @{hardware_type='Cpu'; hardware='CPU'; name='Core (Tctl/Tdie)'; type='Temperature'; value=50},
    @{hardware_type='Cpu'; hardware='CPU'; name='Cores (Average)'; type='Clock'; value=5400},
    @{hardware_type='Cpu'; hardware='CPU'; name='Bus Speed'; type='Clock'; value=100},
    @{hardware_type='SuperIO'; hardware='Board'; name='Fan #1'; type='Fan'; value=0},
    @{hardware_type='SuperIO'; hardware='Board'; name='Bogus'; type='Temperature'; value=[double]::NaN}
)
$s = ConvertTo-HardwareSnapshot $rows
Assert-Equal $s.cpu_temperature_c 50 'Must select CPU Tctl/Tdie, not board or CCD'
Assert-Equal $s.cpu_frequency_mhz 5400 'Must use core frequency, not bus speed'
Assert-Equal $s.sensors.Count 4 'Only finite temperature/fan sensors'
Assert-Equal ($s.sensors | Where-Object kind -eq 'fan').value 0 'Zero RPM is valid'
if (-not $s.sampled_at.EndsWith('Z')) { throw 'Snapshot must use UTC timestamp' }
$empty = ConvertTo-HardwareSnapshot @()
Assert-Equal $empty.cpu_temperature_c $null 'Missing CPU temperature is null'
Assert-Equal $empty.cpu_frequency_mhz $null 'Missing CPU frequency is null'
Assert-Equal $empty.sensors.Count 0 'Empty sensors stay an array'
$tempDir = Join-Path $env:TEMP ('stella-bridge-' + [guid]::NewGuid())
New-Item -ItemType Directory $tempDir | Out-Null
try {
    $target = Join-Path $tempDir 'sensors.json'
    Write-HardwareSnapshot $s $target
    $read = Get-Content -Raw $target | ConvertFrom-Json
    Assert-Equal $read.cpu_temperature_c 50 'First atomic write is readable'
    Write-HardwareSnapshot $empty $target
    $read = Get-Content -Raw $target | ConvertFrom-Json
    Assert-Equal $read.cpu_temperature_c $null 'Replacement clears missing readings'
    Assert-Equal @(Get-ChildItem $tempDir -Filter '*.new').Count 0 'No temp-file leftovers'
} finally { Remove-Item -Recurse -Force $tempDir }
Write-Output 'PASS hardware bridge: CPU identity, clock, finite/null/zero, UTC, atomic create/replace'
