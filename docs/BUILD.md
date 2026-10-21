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
node --test tests/test_voice_guide.mjs tests/test_project_ui.mjs
```

Node is only needed for UI source tests, not by the installed application. Native resource tests use the
Windows .NET Framework C# compiler at its standard Framework64 path. The desktop host targets .NET
Framework 4.6.2 or later and uses the pinned Microsoft WebView2 SDK package described below.
Do not run the production app from the release source directory: keep its audited initial data intact.

## Desktop window

`installer/AppLauncher.cs` owns startup, the installation-specific mutex/activation message, tray icon,
window placement, job confirmation and server process tree. `StudioWebView.cs` owns local navigation,
media windows and Save dialogs. `DesktopPolicy.cs` contains pure origin/identity/placement decisions;
`DesktopRuntime.cs` is shared by setup and launcher for Evergreen detection. Direct `app.py` startup
still uses the normal browser, and the loopback Host/Origin middleware is unchanged.

`installer/webview2.json` pins SDK 1.0.4258.31, its official NuGet URL, package SHA-256 and the hashes of
the two net462 assemblies and x64 loader. `tools/webview2.py` restores only those three DLLs under
`build/webview2`, verifies the included license, and fails on changed cache/package bytes. Build and
native tests reuse `downloads/` when available; first restoration needs the pinned 9.4 MiB package.
The runtime itself is separate from this SDK and is not embedded.

Setup checks the official per-user/per-machine Evergreen registry keys. If missing, it requests consent,
downloads Microsoft's Evergreen bootstrapper, validates its Authenticode signature and exact Microsoft
signer before execution, and rechecks runtime availability. A read-only file handle denies writes and
replacement from signature verification until the bootstrapper exits. This mutable vendor bootstrapper is verified
by its Windows signature rather than an evergreen content hash. The consent installs a shared Microsoft
component, which is deliberately preserved by the application's uninstaller. A missing runtime is a
clear startup error, with no silent switch to another browser.

The dedicated profile/placement folder `.desktop` is installation-local and excluded from source and
payload. Uninstaller traversal removes a junction itself, without following it into a different profile.
The UI requests no remote-debugging port or sandbox-disabling options. Native modal Save UI is scheduled
after the WebView2 event callback, using a deferral; no nested modal loop is entered inside that callback.

`tests/test_desktop.py` compiles a test-only host with the same production sources and uses invented HTML
and a fake backend on an ephemeral port. It checks busy/queued cancellation, unknown status, idle exit,
host crash, actual embedded-browser termination with backend preservation and window recreation,
second-instance activation, saved placement, URL boundaries, SDK tampering and vendor-signature/file-lock
verification. Normal exit checks also reject the forced-browser-stop diagnostic. No AI engine is started.
Lifecycle checks require an already installed WebView2 Runtime and
are skipped explicitly when it is unavailable. Tests never run the runtime installer or alter registry keys.

## Project transfer checks

`app/project_package.py` owns the bounded archive schema, `app/project_transfer.py` owns pure merge
previews and journalled transactions, and `app/project_api.py` owns native dialogs and preview tokens.
`app/project_access.py` provides concurrent readers and exclusive project changes; dialogs are outside
the gate, while transfer reservations prevent worker starts without blocking status polling.
The existing sequential worker must be idle during transfers. Startup recovers interrupted transactions
before it starts. See [PROJECT_FORMAT.md](PROJECT_FORMAT.md) for limits and restoration semantics.

Run the application tests above, including `test_project_transfer.py`, only with disposable synthetic data.
Do not test imports against the audited release source or a user's live installation. No extra dependency
or browser upload support is needed; the installed Python already supplies tkinter, ZIP and JSON support.
Project files, backups and transaction journals are runtime data excluded by the source allowlist.

## Optional video checks

The standalone video renderer uses Pillow 12.3.0, pinned in `requirements.lock` with the Windows x64 /
CPython 3.12 wheel hash. The sequential worker runs video only on request, or after audio export when
automatic video is enabled. The installed renderer prefers
its own `tools/ffmpeg/ffmpeg.exe`; a source checkout uses FFmpeg on PATH. Run video tests with the same
FFmpeg 9.0.2 essentials binaries that setup installs, rather than a different system build:

```powershell
$env:PATH = 'C:\VideoTest\tools\ffmpeg;' + $env:PATH
python -m unittest discover -s app -p test_video.py -v
python -m unittest discover -s app -p test_video_jobs.py -v
python app/video.py "C:\VideoTest\work\The Lantern House\001 - The Message" "C:\VideoTest\preview.mp4" --start 0 --seconds 30
```

Use disposable synthetic chapter files for testing; do not add manuscripts, work data or generated MP4s
to the public source tree. Public README screenshots must use invented text and contain no local paths.
The GUI and CLI share one renderer. Video defaults are supplied in memory for legacy settings files;
initial release settings and reference voices are unchanged. `video_jobs.py` owns chapter cache records,
MP4 publication, measured timing, YouTube lists and scratch ownership. `video.py` owns drawing/encoding.
Neither starts a voice engine. Frames belong in `work/video-temp`, never beside the final export.
Intermediate MP4s use owned `export/<volume>/video/.video-temp` folders; startup cleanup covers both
locations. Streams and container duration must match chapter audio within 80 ms before publication.
The automation switch is excluded from render options, cache keys and measured timing comparisons.

## Native runtime

The pinned engine commit and build settings are in `native/upstream.json`. The release's exact native
source archive includes ggml and the custom `spk-batch` tool. The additional CMake target links qwen-core
and ggml backends. Source and MIT notices accompany the binary release.

`manifest.json` is the single source for the CUDA targets and minimum driver (`hardware`). The helper
reads that policy: native targets 75, 80, 86, 89 and 120, with PTX at 75. The pinned ggml CMake code
specializes 120 to `120a-real` for Blackwell instructions. The installer and setup window use the same
manifest list for eligibility; an unlisted compute capability is refused instead of assumed compatible.
Compiling these targets does not replace physical tests on the corresponding cards.

To reuse the exact engine from a verified release, start with an empty `build/native` directory:

```powershell
powershell -NoProfile -File tools/restore_native.ps1 -Installer C:\Releases\AudioBookStudio-Setup.exe
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
`dist/` receives the setup, public source, exact native source and `SHA256SUMS.txt`.
Product documentation and license notices are included inside the archives and application payload.
`--reuse-payload` is accepted only when all payload inputs still match their recorded hashes.

Validate the generated installer in an isolated installation. The build process does not sign files
or upload a GitHub release. Review every distribution asset before sharing it.

Publish one rolling release, **AudioBook Studio**, using tag `current` and the stable installer name
`AudioBookStudio-Setup.exe`. Replace all assets and point `current` at the reviewed source commit together.
The branch commit history records development; there is no sequence of numbered public downloads.
Internal installer/project schema versions remain compatibility markers and are not download labels.
Prepare replacement assets in a draft before replacing the visible current release, so downloads are
not offered with mismatched checksums/source. Do not upload stale files from previous local builds.

Publish only these four release assets:

- `AudioBookStudio-Setup.exe`.
- `AudioBookStudio-source.zip`, matching the release tag's reviewed source tree.
- `AudioBookStudio-native-source.zip`, containing the exact native engine source and its licenses.
- `SHA256SUMS.txt`, listing the SHA-256 of those three files with their published names.

Keep documentation and license notices in the repository and archives; do not upload extra copies
as release attachments. GitHub also adds its own source archive links automatically.
