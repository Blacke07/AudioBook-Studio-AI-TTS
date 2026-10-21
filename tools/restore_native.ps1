param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
$kitRoot = Split-Path -Parent $PSScriptRoot
$nativeRoot = [IO.Path]::GetFullPath((Join-Path $kitRoot 'build\native'))
$assembly = [Reflection.Assembly]::LoadFile([IO.Path]::GetFullPath($Installer))
$stream = $assembly.GetManifestResourceStream('payload.zip')
if ($null -eq $stream) { throw 'The executable does not contain the expected payload.' }
try {
    $archive = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Read)
    try {
        foreach ($entry in $archive.Entries) {
            if (-not $entry.FullName.StartsWith('engine/')) { continue }
            $destination = [IO.Path]::GetFullPath((Join-Path $nativeRoot $entry.FullName))
            if (-not $destination.StartsWith($nativeRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid archive path.' }
            if (Test-Path -LiteralPath $destination) { throw "The file already exists: $destination. Refusing to overwrite it." }
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            $inputStream = $entry.Open()
            $outputStream = [IO.File]::Create($destination)
            try { $inputStream.CopyTo($outputStream) } finally { $inputStream.Dispose(); $outputStream.Dispose() }
        }
    } finally { $archive.Dispose() }
} finally { $stream.Dispose() }
Write-Output 'Native runtime restored from the release into build/native.'
