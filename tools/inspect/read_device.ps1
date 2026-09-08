param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9-]{6,32}$')][string]$ExpectedUsbSerial
)
$ErrorActionPreference = 'Stop'
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($taskOutput) | Out-Null
$taskResult = Join-Path $taskOutput 'inspection.json'
try {
    $taskDevices = @(Get-CimInstance Win32_DiskDrive | Where-Object {
        $_.Model -eq 'Apple iPod USB Device' -and
            $_.PNPDeviceID.IndexOf($ExpectedUsbSerial,[StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    if ($taskDevices.Count -ne 1) { throw 'Expected exactly one observed iPod hardware identity.' }
    $taskDevice = $taskDevices[0]
    if ($taskDevice.DeviceID -notmatch 'PHYSICALDRIVE(\d+)$') { throw 'Unexpected disk device path.' }
    $taskStorageDisk = Get-Disk -Number ([int]$Matches[1])
    if ($taskStorageDisk.LogicalSectorSize -ne 512) { throw 'Only 512-byte device sectors are supported.' }
    # The physical disk is opened READ ONLY. This utility has no disk write path.
    $taskStream = [IO.FileStream]::new($taskDevice.DeviceID, [IO.FileMode]::Open,
        [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $taskMbr = [byte[]]::new(512)
        if ($taskStream.Read($taskMbr,0,512) -ne 512) { throw 'Short MBR read.' }
        if ($taskMbr[510] -ne 0x55 -or $taskMbr[511] -ne 0xaa) { throw 'Invalid MBR signature.' }
        [IO.File]::WriteAllBytes((Join-Path $taskOutput 'mbr.bin'),$taskMbr)
        $taskPartitions = @()
        for ($taskIndex=0; $taskIndex -lt 4; $taskIndex++) {
            $taskOffset=446+$taskIndex*16
            $taskType=[int]$taskMbr[$taskOffset+4]
            $taskLba=[BitConverter]::ToUInt32($taskMbr,$taskOffset+8)
            $taskSectors=[BitConverter]::ToUInt32($taskMbr,$taskOffset+12)
            if ($taskSectors -eq 0) { continue }
            $taskBytes=[long]$taskSectors*512
            if (([long]$taskLba*512+$taskBytes) -gt [long]$taskStorageDisk.Size) { throw 'Partition outside actual device capacity.' }
            $taskPart=@{index=$taskIndex;type=$taskType;lba=$taskLba;sectors=$taskSectors}
            if ($taskType -notin @(0x0b,0x0c,0x06,0x0e)) {
                if ($taskBytes -gt 268435456) { throw 'Non-media partition exceeds the 256 MiB inspection bound.' }
                $taskPath=Join-Path $taskOutput "firmware-partition-$taskIndex.bin"
                $taskBackup=[IO.FileStream]::new($taskPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
                try {
                    $null=$taskStream.Seek([long]$taskLba*512,[IO.SeekOrigin]::Begin)
                    $taskBuffer=[byte[]]::new(65536)
                    $taskRemaining=$taskBytes
                    while ($taskRemaining -gt 0) {
                        $taskWanted=[int][Math]::Min($taskRemaining,$taskBuffer.Length)
                        $taskRead=$taskStream.Read($taskBuffer,0,$taskWanted)
                        if ($taskRead -le 0) { throw 'Short firmware partition read.' }
                        $taskBackup.Write($taskBuffer,0,$taskRead)
                        $taskRemaining-=$taskRead
                    }
                    $taskBackup.Flush($true)
                } finally { $taskBackup.Dispose() }
                $taskPart.backup=$taskPath
                $taskPart.sha256=(Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            $taskPartitions += $taskPart
        }
        @{passed=$true;read_only=$true;device=$taskDevice.DeviceID;model=$taskDevice.Model;
            serial_number=$taskDevice.SerialNumber;pnp_id=$taskDevice.PNPDeviceID;
            partitions=$taskPartitions} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $taskResult -Encoding utf8
    } finally { $taskStream.Dispose() }
} catch {
    @{passed=$false;read_only=$true;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $taskResult -Encoding utf8
    exit 1
}
