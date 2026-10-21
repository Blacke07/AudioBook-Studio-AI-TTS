# Build on Windows

End users need only the setup EXE. These instructions are for maintainers.

## Python and source checks

Use Python 3.12 x64 and install `requirements.lock` in a development environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements.lock
.\.venv\Scripts\python.exe -m unittest discover -s app -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node --check app/web/app.js
node --test tests/test_voice_guide.mjs
```

Node is only needed for UI source tests, not by the installed application. Native resource tests use the
Windows .NET Framework C# compiler at its standard Framework64 path; no NuGet packages are required.
Do not run the production app from the release source directory: keep its audited initial data intact.

## Native runtime

The pinned engine commit and build settings are in `native/upstream.json`. The release's exact native
source archive includes ggml and the custom `spk-batch` tool. The additional CMake target links qwen-core
and ggml backends. Source and MIT notices accompany the binary release.

To reuse the exact engine from a verified release, start with an empty `build/native` directory:

```powershell
powershell -NoProfile -File tools/restore_native.ps1 -Installer C:\Releases\AudioBookStudio-Setup-1.0.0.exe
```

To compile, install licensed Visual Studio 2022 Build Tools with the VC142 14.29 toolset, CMake/Ninja,
and CUDA Toolkit 12.8. Use a neutral build workspace to avoid embedding personal home paths in assertions.
The checked-in helper expects the full exact source archive, not a GitHub snapshot missing ggml:

```powershell
powershell -NoProfile -File tools/build_native.ps1 -SourceArchive C:\Releases\AudioBookStudio-native-source.zip -CudaRoot 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8' -VcVars 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat' -Workspace C:\AudioBookStudioBuild
```

The helper builds `tts-server.exe`, `spk-batch.exe` and ggml DLLs into `build/native/engine/build`.
Add only the app-local redistributable VC142 runtime DLLs from your licensed toolset, not compilers.
Add these CUDA 12.8 redistributables under `build/native/engine/cuda`:

- `cudart64_12.dll`
- `cublas64_12.dll`
- `cublasLt64_12.dll`

The release's native payload also contains `msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll`
and `vcomp140.dll`. Keep the bundled notices. Do not copy the CUDA SDK or a complete Visual Studio toolchain.
Check the exact vendor licenses before changing the runtime set.

Place the exact native source ZIP at `build/native-source.zip`. To export it from a full prepared source tree:

```powershell
python tools/export_native_source.py --source C:\AudioBookStudioBuild\source\engine --output build/native-source.zip
```

## Demo and release build

The checked-in narrator WAV and calibration are newly generated synthetic public assets. Do not replace
them with personal reference recordings. `demo-provenance.json` and `release-state.json` lock their hashes.
To intentionally create a different demo, use `tools/make_demo.py --models-dir ...` with the pinned models,
review the new audio and update the initial-state manifest intentionally. This is not needed for normal builds.

```powershell
python tools/audit_public.py
python tools/build.py
python tools/package_repository.py
```

The build creates the launcher, the uninstaller and icon, bundles the app/native runtime, embeds that payload in the setup
EXE, and checks embedded resources. Model weights and downloaded vendor packages are not embedded.
`dist/` contains the setup, public source, exact native source, docs and SHA-256 checksums.
`--reuse-payload` is accepted only when all payload inputs still match their recorded hashes.

Validate the generated installer in an isolated installation. The build process does not sign files
or upload a GitHub release. Review every distribution asset before sharing it.
