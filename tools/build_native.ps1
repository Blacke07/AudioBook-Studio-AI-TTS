param(
    [Parameter(Mandatory=$true)][string]$SourceArchive,
    [Parameter(Mandatory=$true)][string]$CudaRoot,
    [Parameter(Mandatory=$true)][string]$VcVars,
    [string]$Workspace = 'D:\AudioBookStudioBuild',
    [string]$CMake = 'cmake.exe'
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$hardware = (Get-Content -LiteralPath (Join-Path $project 'manifest.json') -Raw | ConvertFrom-Json).hardware
$architectures = @($hardware.cuda_architectures)
if ($architectures.Count -eq 0 -or $hardware.ptx_architecture -notin $architectures) {
    throw 'The manifest must specify native CUDA architectures and one matching PTX architecture.'
}
$targets = @($architectures | ForEach-Object {
    if ([string]$_ -notmatch '^[1-9][0-9]{1,2}$' -or $_ -lt 75) { throw 'Invalid CUDA architecture in manifest.json.' }
    if ($_ -eq $hardware.ptx_architecture) { [string]$_ } else { "$_-real" }
}) -join ';'
$work = [IO.Path]::GetFullPath($Workspace)
if (Test-Path -LiteralPath $work) { throw 'Choose a new empty build workspace. Existing builds will not be overwritten.' }
foreach ($file in @($SourceArchive, (Join-Path $CudaRoot 'bin\nvcc.exe'), $VcVars)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing build input: $file" }
}
New-Item -ItemType Directory -Path $work | Out-Null
Expand-Archive -LiteralPath $SourceArchive -DestinationPath (Join-Path $work 'source')
$source = Join-Path $work 'source\engine'
if (-not (Test-Path -LiteralPath (Join-Path $source 'tools\spk-batch.cpp'))) { throw 'The exact native source archive is required.' }
$script = Join-Path $work 'build.cmd'
$cuda = [IO.Path]::GetFullPath($CudaRoot)
$lines = @(
    '@echo off',
    "call `"$VcVars`" -vcvars_ver=14.29",
    'if errorlevel 1 exit /b 1',
    "set `"PATH=$cuda\bin;%PATH%`"",
    "`"$CMake`" -S `"$source`" -B `"$work\build`" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_COMPILER=`"$cuda\bin\nvcc.exe`" `"-DCMAKE_CUDA_ARCHITECTURES=$targets`" -DGGML_CUDA=ON -DGGML_CUDA_FA_ALL_QUANTS=OFF -DGGML_NATIVE=OFF -DGGML_AVX2=ON -DGGML_AVX512=OFF",
    'if errorlevel 1 exit /b 1',
    "`"$CMake`" --build `"$work\build`" --config Release --target tts-server spk-batch -j 2"
)
Set-Content -LiteralPath $script -Value $lines -Encoding ASCII
& $env:ComSpec /d /c $script
if ($LASTEXITCODE -ne 0) { throw 'Native compilation failed. No release files were copied.' }
$output = Join-Path $project 'build\native\engine\build'
New-Item -ItemType Directory -Path $output -Force | Out-Null
foreach ($name in @('tts-server.exe','spk-batch.exe','ggml.dll','ggml-base.dll','ggml-cpu.dll','ggml-cuda.dll')) {
    $files = @(Get-ChildItem -LiteralPath (Join-Path $work 'build') -Filter $name -Recurse -File)
    if ($files.Count -ne 1) { throw "Expected exactly one compiled $name" }
    Copy-Item -LiteralPath $files[0].FullName -Destination (Join-Path $output $name)
}
Write-Output 'Compiled engine copied. Add licensed app-local VC142 and CUDA runtime DLLs, then run the public audit.'
