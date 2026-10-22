param(
    [Parameter(Mandatory=$true)][string]$Target,
    [string]$ModelsSource = '',
    [string]$InstallerPath = '',
    [ValidateScript({ $_ -cmatch '^[a-z]*$' })][string]$Profile = '',
    [switch]$Manual,
    [switch]$Download,
    [switch]$CheckTarget,
    [switch]$CheckModels,
    [switch]$AcceptLicenses
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    $installRoot = [IO.Path]::GetFullPath($Target)
    if ($installRoot.TrimEnd('\') -eq [IO.Path]::GetPathRoot($installRoot).TrimEnd('\')) {
        throw 'Move the EXE into a dedicated application folder, not the drive root.'
    }
    $installRoot = $installRoot.TrimEnd('\')
    foreach ($relative in @('','Data','Data\Program','Data\User','Data\State','models')) {
        $ownedPath = if ($relative) { Join-Path $installRoot $relative } else { $installRoot }
        if ((Test-Path -LiteralPath $ownedPath) -and ((Get-Item -LiteralPath $ownedPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Installation folders must not be links or junctions.'
        }
    }
    if ($InstallerPath -and ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($InstallerPath)) -ne $installRoot)) {
        throw 'The destination must be the folder containing the EXE.'
    }
    if ($installRoot.Length -gt 140) { throw 'Choose a shorter installation folder; the Windows tools have path-length limits.' }
    $sessionMarker = Join-Path $installRoot 'Data\State\.studio-install-incomplete'
    $oldMarker = Join-Path $installRoot '.studio-install-incomplete'
    foreach ($checkMarker in @($sessionMarker,$oldMarker)) {
        if ((Test-Path -LiteralPath $checkMarker) -and ((Get-Content -LiteralPath $checkMarker -Raw).Trim() -ne 'AudioBookStudio-Installer-1')) {
            throw 'Invalid installation marker. No files were changed.'
        }
    }
    $knownInstall = $false
    foreach ($manifestFile in @((Join-Path $installRoot 'Data\State\installation-manifest.json'), (Join-Path $installRoot 'installation-manifest.json'))) {
        if (Test-Path -LiteralPath $manifestFile) {
            $known = Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
            if ($null -eq $known.payload_files -or $null -eq $known.initial_state_files -or $null -eq $known.models) { throw 'Invalid installation manifest.' }
            $knownInstall = $true
        }
    }
    if ((Test-Path -LiteralPath $installRoot) -and -not $knownInstall -and -not (Test-Path -LiteralPath $sessionMarker)) {
        $releaseFiles = @('AudioBookStudio-Setup.exe','AudioBookStudio-source.zip','AudioBookStudio-native-source.zip',
            'README.md','VERIFICATION.md','SHA256SUMS.txt','THIRD_PARTY_NOTICES.md','PRIVACY.md','LICENSE')
        foreach ($entry in Get-ChildItem -LiteralPath $installRoot -Force) {
            if ($entry.PSIsContainer -and $entry.Name -eq 'models') { continue }
            if (-not $entry.PSIsContainer -and $InstallerPath -and $entry.FullName -eq [IO.Path]::GetFullPath($InstallerPath)) { continue }
            if (-not $entry.PSIsContainer -and $entry.Name -in $releaseFiles) { continue }
            throw "Unrecognized files ($($entry.Name)). Use a new folder or an existing AudioBook Studio installation with its manifest."
        }
    }
    if ($CheckTarget) { Write-Output 'Valid destination. No files were created or modified.'; exit 0 }
    if (-not $AcceptLicenses) { throw 'Component licenses must be accepted before installation.' }
    if ($Manual -and $Download) { throw 'Choose either supplied models or automatic downloads.' }
    $localModels = Join-Path $installRoot 'models'
    if (-not $Manual -and -not $Download -and (Test-Path -LiteralPath $localModels -PathType Container)) {
        # The folder setup prepares holds only its instruction file until the user adds model files.
        $supplied = @(Get-ChildItem -LiteralPath $localModels -Recurse -File -Force | Where-Object { $_.Name -ne '_place models here' -and $_.Name -notlike '*.part' })
        if ($supplied.Count -gt 0) {
            $Manual = $true
            $ModelsSource = $localModels
            Write-Output 'Using models in the models subfolder. All files will be verified.'
        } else {
            Write-Output 'models contains no model files yet; models will be downloaded automatically.'
        }
    }
    if ($CheckModels) { Write-Output ('Model source: ' + $(if ($Manual) { 'manual' } else { 'download' })); exit 0 }
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    foreach ($ownedProcess in Get-CimInstance Win32_Process) {
        if ($ownedProcess.ExecutablePath -and $ownedProcess.ExecutablePath.StartsWith($installRoot+'\',[StringComparison]::OrdinalIgnoreCase) -and $ownedProcess.ExecutablePath -ne $InstallerPath) { throw 'Close AudioBook Studio and its tools before updating.' }
    }
    $stateFolder = Join-Path $installRoot 'Data\State'
    New-Item -ItemType Directory -Path $stateFolder -Force | Out-Null
    if (-not (Test-Path -LiteralPath $sessionMarker)) { Set-Content -LiteralPath $sessionMarker -Value 'AudioBookStudio-Installer-1' -Encoding ASCII }
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
    $cachePath = Join-Path $env:LOCALAPPDATA 'AudioBookStudio-Installer\downloads'
    New-Item -ItemType Directory -Path $cachePath -Force | Out-Null
    $pythonArchive = Join-Path $cachePath $manifest.python.name
    if (Test-Path -LiteralPath $pythonArchive) {
        if ((Get-FileHash -LiteralPath $pythonArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.python.sha256) {
            throw "The cached Python archive does not match the manifest. Remove only this file and retry: $pythonArchive"
        }
    } else {
        Write-Output 'Downloading portable Python for this application...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $webClient = New-Object Net.WebClient
        try { $webClient.DownloadFile($manifest.python.url, $pythonArchive + '.part') }
        finally { $webClient.Dispose() }
        if ((Get-FileHash -LiteralPath ($pythonArchive + '.part') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.python.sha256) {
            throw 'Python download failed SHA-256 verification.'
        }
        Move-Item -LiteralPath ($pythonArchive + '.part') -Destination $pythonArchive
    }
    $runtimePath = Join-Path $installRoot 'Data\Program\runtime'
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    Write-Output 'Extracting Python without changing the system Python or PATH.'
    & "$env:SystemRoot\System32\tar.exe" -xf $pythonArchive -C $runtimePath
    if ($LASTEXITCODE -ne 0) { throw 'Python extraction failed.' }
    $pythonPath = Join-Path $runtimePath 'python\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'The Python archive has an unexpected layout.' }
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $coreArgs = @((Join-Path $PSScriptRoot 'install.py'), '--target', $installRoot, '--bundle', (Join-Path $PSScriptRoot 'payload.zip'), '--manifest', (Join-Path $PSScriptRoot 'manifest.json'), '--cache', (Join-Path $installRoot 'Data\State\downloads'))
    if ($Manual) { $coreArgs += @('--manual-models', $ModelsSource) }
    if ($Profile) { $coreArgs += @('--profile', $Profile) }
    & $pythonPath @coreArgs
    if ($LASTEXITCODE -ne 0) { throw "Installation did not complete. See the log at $installRoot\Data\State\logs\install.log" }
    Write-Output 'INSTALLATION COMPLETE. Start AudioBook Studio.exe from the installation folder.'
    exit 0
} catch {
    Write-Output ('ERROR: ' + $_.Exception.Message)
    exit 1
}
