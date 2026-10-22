# Compatibility and validation

AudioBook Studio runs locally on Windows 10/11 x64 with an AVX2-capable CPU and an NVIDIA GPU.
The native engine contains CUDA targets 7.5, 8.0, 8.6, 8.9 and 12.0. The Blackwell target is specialized
as 120a by the native build. NVIDIA driver 570.65 or newer is required.

| Model set | VRAM | Status |
| --- | --- | --- |
| Standard | At least 12 GB | Tested on RTX 4080 Laptop, 12 GB |
| Compact | At least 8 GB | Experimental; real-model measurements are pending |

Other GPU targets are compiled into the engine, but have not been tested on physical RTX 20/30/50 cards.
See [NVIDIA's compute capability list](https://developer.nvidia.com/cuda/gpus) for architecture mappings.

## Checks performed

- Application, installer, uninstaller, archive validation and UI helper tests.
- Local server Host/Origin restrictions, model hashes, safe archive extraction and process ownership.
- Native Base fixed-voice, Voice Design and CustomVoice synthesis on RTX 4080 Laptop.
- Regression samples from the expanded GPU build matched the previous engine's WAV files byte for byte.
- CPU and CUDA speaker encoders returned finite 2048-dimensional vectors with matching results.
- Each of the 145 audited CUDA fatbinary blocks contains all five native targets and PTX at 7.5.
- Installer resources, embedded payload, public source contents and distribution SHA-256 checksums.

To run the source tests and reproduce a Windows build, see [docs/BUILD.md](docs/BUILD.md).

## Installation-local model staging

The current packaged source passes 212 Python tests (138 application + 74 distribution) and 12 Node tests.
Six added installer regressions cover moving verified Qwen files and Gemma blobs from `Local Models`
into `models`, retaining the same filesystem file identity without copying model data, retry after an
interrupted transfer, invalid bytes/destination conflicts, junction refusal and preservation of extras.
An explicitly external model library is copied and left unchanged. Post-move verification failures
retain the moved file and report its location. Tests use small invented model bytes and fake runtime
setup/verification; they do not constitute another real-model or clean-Windows installation test.

## Chapter batch selection

The header checkbox reflects all, partial or empty selection after the chapter table redraws.
Clicking it again clears the visible chapters; hidden selections are preserved when filtering.
Each checkbox has a 44-by-44 CSS-pixel label, with a 20-pixel checkbox. Clicking anywhere in its
selection cell selects the chapter without opening it; clicking the title still opens the editor.
Four Node regressions exercise the actual volume renderer and batch payload. Browser checks on an
isolated invented two-chapter volume confirmed select/deselect-all, partial selection, label/cell
clicks and normal chapter navigation. No installed application or private project data was changed.

## Optional video renderer

The current build includes video settings, chapter/volume actions, cache status and an optional video
step in the existing sequential worker. Automatic video defaults to off; the audio-only path is preserved.
No new AI inference or model download was used to test this integration.

- Baseline: 57 application + 54 installer/source tests, and 4 Node tests passed before the port.
- Before GUI integration: 76 application + 54 installer/source tests (130 Python total), and 4 Node tests.
- Before project transfer: 102 application + 54 installer/source tests (156 Python total), and 4 Node tests passed.
- The renderer has 19 tests: timeline boundaries and gaps, omitted tags, long text and names, wrapping,
  transition continuity, cache inputs/lifetime, public file layout and the generic CLI.
- Another 26 integration tests cover strict video settings and legacy settings, current/outdated cache,
  interrupted/resumed jobs, actual FFmpeg cancellation, low-space refusal, safe scratch ownership and cleanup
  after an abruptly terminated subprocess, export-before-video ordering, per-chapter errors, measured-only
  estimates, local API restrictions and YouTube timestamps. No real manuscript is used.
- Encoder selection performs a real NVENC probe and falls back to libx264. Tests use the pinned Gyan
  FFmpeg 9.0.2 essentials archive from the installer manifest, verified by SHA-256.
- That build provides h264_nvenc, libx264, AAC, the fps filter and the concat demuxer. A real synthetic
  encode verifies H.264/AAC, yuv420p, BT.709/tv, 1080p/30 fps and separate video/audio durations and frame count.
- Speaker colour hashing is compared with the public UI's actual JavaScript implementation, including Unicode.
- The public screenshot and local layout clip use invented dialogue. The clip contains a mathematical test tone;
  no AI engine was started and no private text, voice samples or generated chapters were imported.
- Settings, Chapter and Volume were inspected in the browser using disposable synthetic data. Saving video
  settings, chapter creation, volume creation, cache reuse and the YouTube list were exercised through the UI.
- Two synthetic 24-second chapters rendered with NVENC in 4.279 and 3.976 seconds on the development machine.
  These are local examples, not a general speed guarantee. The first starts at 00:00, the second at 00:24.
- Automation is excluded from the shared render-options fingerprint and measured timing comparison.
  An actual encode with both streams too short is refused before replacing the previous video/record.
- Scratch PNGs stay under `work/video-temp`. The intermediate MP4 uses an owned staging folder under
  `export/<volume>/video/.video-temp`, so space is checked on the actual export drive and final publication
  stays on that drive. Ownership markers and live-process checks limit restart cleanup to abandoned folders
  in both locations. A terminated subprocess during the cross-device copy branch leaves a temporary file
  that startup cleanup removes; device comparison is simulated so this test also runs on one-drive machines.
  Space checks sample PNG sizes with a margin and reserve MP4 space. They
  cannot guarantee against unrelated software filling the disk after the check.

These are source and local-runtime checks, not a clean-Windows installation test. Full-volume rendering,
YouTube's re-encoding and physical additional-GPU performance remain unverified. Low-disk and abandoned
scratch recovery have synthetic tests; clean-Windows installation and a long real book remain unverified.
Full-volume MP4 concatenation is deferred, so stream-compatibility/concatenation tests are not claimed.

## Project import and export

The current build has an English Project page and version 1 `.abstudio` archives. No old application
code is executed. Transfers are refused while jobs are queued or running; settings require explicit selection
and existing characters, fixed voices and speaker corrections are kept unless individually overridden.

- 138 application + 54 installer/source tests (192 Python total), and 8 Node tests pass.
- The 21 initial project Python tests cover round trips and reference hashes, zero-write previews, each conflict rule,
  source-hash mismatch, missing/located folders, UNC refusal, corrupt WAVs and IDs, hostile ZIP paths,
  duplicates, links, size limits, future versions, unknown fields, exact Undo, stale previews, modified backups,
  mid-transaction failures and recovery after a real abruptly terminated subprocess.
- API tests exercise preview/apply/export/Undo, explicit confirmation, busy queues, changed archives and
  foreign-origin rejection before any dialog. Four project Node tests exercise the actual page renderer:
  escaped untrusted content, conservative defaults, invalidated choices, cancelled confirmation and
  privacy warnings for reference transcripts/notes even without book assignments.
- Another 15 Python regression tests reproduce and check review corrections: no persistence/probing of
  untrusted non-local sources, correct-hash scripts with altered text refused, unchanged segmented text
  retained, punctuation/long display names through export/backup/Undo, shared invalid-name rules,
  live readers/status during slow dialogs and auditions, post-dialog queue recheck, exclusive import
  readers, cancellation and writer priority. An unknown recovery owner deliberately fails without writes.
- The browser flow was exercised on an isolated copy with invented cast and chapter text: export,
  import preview, folder relocation, optional settings, apply, visible imported volume and Undo. Native file
  dialogs were replaced with deterministic local results in this test harness only. Interactive native
  dialog appearance and a clean installed Windows environment remain unverified.
- Transactions stage all bytes and original versions before replacement. Other API readers wait only for
  exclusive project changes, rather than being serialized with each other or with native dialogs;
  startup restores unfinished transactions before starting the worker. The tests cover process termination,
  not power-loss or filesystem corruption guarantees. Undo saves an additional safety backup first.
- Project packages, automatic backups, reports and journals are excluded from public source and setup.
  Cast-only exports omit the dedicated real-book examples; reference transcripts and notes still require review.

See [docs/PROJECT_FORMAT.md](docs/PROJECT_FORMAT.md) for the archive schema and explicit size limits.

## Desktop window

The desktop launcher embeds the existing interface in Microsoft WebView2, without browser tabs or an
address bar. Direct Python development startup still uses the normal browser. This change neither
modifies the audio pipeline nor changes approved initial settings or synthetic reference voices.

- Before this change: 192 Python tests (138 application + 54 distribution) and 8 Node tests passed.
- Desktop integration and review corrections passed 206 Python tests (138 application + 68 distribution)
  and 8 Node tests; the six model-staging tests above bring the current total to 212 Python tests.
- Thirteen desktop tests use the actual native host and WebView2 with invented HTML and a fake backend:
  origin/profile/identity decisions, tampered SDK rejection, Microsoft signature checking, idle exit,
  running/queued work cancellation and confirmation, unavailable status, host crash, second-instance
  restoration and saved window placement. Three terminate the actual embedded browser, preserve the
  running/queued backend or unknown-status confirmation, cancel exit, recreate the window and then
  confirm exit. Normal exits do not log a timeout/forced browser stop. A new uninstaller regression protects a different browser
  profile behind a junction. No Qwen/Gemma inference or runtime installation is used in these tests.
- The real interface was viewed in an isolated window using the existing development machine's WebView2
  Runtime. Native title/icon and dark caption, local navigation, an owned video window, native Save and
  a completed synthetic chapter-list download were checked. The actual exit confirmation was viewed;
  Cancel preserved the simulated active job and server. The Project chooser reached import preview;
  no import was applied to that disposable copy.
- The SDK archive, three redistributable DLLs and license are pinned. The Evergreen bootstrapper's
  signature verifier was tested with a signed Microsoft component and an invalid candidate; neither
  candidate was executed. Writes and deletion of the verified file are refused while its handle is held.
  The real download/install-on-missing-runtime path is not exercised here.
- Taskbar identity uses Windows' EXE/shortcut inference, avoiding an explicit application ID absent from
  setup's shortcuts. Actual pinning/grouping across Windows versions is still unconfirmed.
- The dedicated `.desktop` directory is excluded from public source and payload; uninstall removes it
  without deleting the shared Microsoft runtime or following links to other browser profiles.

These are development-machine checks. A clean Windows install, a machine without WebView2 Runtime,
interactive runtime-install consent/error recovery, taskbar pinning/grouping across Windows versions,
tray-menu interaction and native chooser foreground behavior on other machines remain unconfirmed.
No default browser profile is used for the embedded interface. Third-party runtime network behavior
is separate from local model inference; see [PRIVACY.md](PRIVACY.md).

## Limits

The installer is unsigned. Installation on a clean Windows system and uninstallation of a real
installation still require validation. Compact has not been measured for VRAM use, speed, dialogue
accuracy or audition quality on an 8 GB card.

Automatic tests do not certify voice quality or correct dialogue attribution. Review uncertain speaker
assignments and listen to important passages before exporting a complete audiobook.
