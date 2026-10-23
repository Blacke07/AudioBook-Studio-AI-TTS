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

## Installed folders and safe updates (2026-10-22)

The installed layout separates `Data/Program`, `Data/User` and `Data/State`; finished media is under
`Audiobooks`, private snapshots under `Backups`, and models remain in `models` without duplicate copies.
The initial release settings/reference bytes are unchanged. Application tests use the same logical
media URLs while checking their new physical destinations and rejecting paths outside the allowed roots.

- 168 application + 96 distribution tests (264 Python total), and 27 Node tests passed locally.
- Legacy fixtures retain settings, fixed WAVs, scripts, generated audio, exports and external books.
  Every move boundary and the ready-before-commit boundary were interrupted and resumed; rollback,
  destination conflicts, changed files, invalid references and unfinished Project imports were exercised.
  An unfinished Project import is explicitly refused before moving anything; recover it in the existing
  app first. Internal source locations are remapped; old snapshot archives themselves are not rewritten.
- Synthetic program publication verifies staging hashes, journal/preimages, resume, rollback and a
  reinstall that keeps user settings instead of overwriting them with the public demo state.
- A synthetic old backup was previewed without writes, applied, interrupted and resumed with the reviewed
  plan hash. WAVs/audio/export bytes were verified, modification times preserved, and old code/models
  excluded. Tampered backup data was refused before changing the restored data. Restore preimages are retained.
- Uninstaller fixtures exercise both layouts. Default removal keeps user data, audiobooks, backups and
  models; explicit data deletion does not delete the other categories. Existing identity metadata allows
  reinstall. Linked parent folders are refused before removal; browser-profile links never delete their targets.
  A preimage-directory junction regression also refuses a program update before it can write outside the installation.
- The actual compiled launcher resolves its SDK from Data/Program with no root-level DLL copies.
  Native desktop lifecycle tests still use the real installed WebView2 Runtime and synthetic backends.
- Folder actions target the external chapter source, Audiobooks, chapter work and the video file's folder.
  The native-runtime restoration helper accepts both old and new release payload layouts.
- Paths beyond 260 characters were tested for an explicit early refusal without output. The app uses a
  conservative 240-character limit for affected file/tool paths; setup also refuses a very long root.
  This does not claim extended-path support for every Windows component and changes no system policy.

These are synthetic/local checks, not an installation on a clean Windows computer or a restoration of
the owner's real backup. Those remain separate guided steps; no new speech inference or model download
was used for the layout change. Existing Undo records/backups retain their original data: a remapped
internal source can require Locate folder or a new preview rather than silently rewriting old history.
## Models in the final installation folder

Model-specific checks verify in-place reuse alongside the full source checks listed above.
Setup creates `models` directly. Exact Qwen files and Gemma blobs supplied there are verified and used
in place, without a transfer or a second copy. Tests assert unchanged filesystem file identity on a
second run and reject any attempt to transfer already supplied models. Invalid files and linked
destinations are rejected; unknown files survive uninstall. An explicitly external model library is
copied and left unchanged. Model downloads use their final directory and a verified `.part` file.
These tests use small invented bytes and fake runtime setup/verification, not real models or a clean PC.

## Ordered workflow and manual recovery

Text, Audio and Video actions are grouped in numbered disclosures. Hover shows actions; clicking also
shows explanations. Every chapter in the selected batch must satisfy the preceding stage. The backend
checks prerequisites both before queueing and at execution. Automatic runs pause the whole batch when
text needs review. The explicit Reading option to use the narrator for unresolved dialogue is preserved.

Speaker response schemas constrain batch length and row IDs. Invalid responses apply no assignments;
text-free diagnostics record batch counts and missing row numbers. An explicit repair uses batches of
three dialogue lines. Text and speaker controls remain available without a successful AI analysis.
Manual saves and splits verify the current source hash and unchanged text; viewing a draft writes nothing.
These checks use synthetic text and mocked responses. The owner's failed chapters have not been rerun,
and real-model success with the revised schema is not claimed.

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
- The renderer has 23 tests: timeline boundaries and gaps, omitted tags, long text and names, wrapping,
  transition continuity, cache inputs/lifetime, public file layout and the generic CLI.
- Another 28 integration tests cover strict video settings and legacy settings, current/outdated cache,
  interrupted/resumed jobs, actual FFmpeg cancellation, low-space refusal, safe scratch ownership and cleanup
  after an abruptly terminated subprocess, export-before-video ordering, per-chapter errors, measured-only
  estimates, local API restrictions and YouTube timestamps. No real manuscript is used.
- H.264 selection performs a real NVENC probe and falls back to a checked libx264 encoder. H.265 and AV1
  require successful hevc_nvenc / av1_nvenc probes and never fall back to another codec. Failed and successful
  probes are cached per session, time bounded and run outside the UI event loop and project access gate.
  Tests use Gyan
  FFmpeg 9.0.2 essentials archive from the installer manifest, verified by SHA-256.
- That build provides h264_nvenc, libx264, AAC, the fps filter and the concat demuxer. A real synthetic
  encode verifies H.264/AAC, yuv420p, BT.709/tv, 1080p/30 fps and separate video/audio durations and frame count.
- Codec update (2026-10-22): 165 application + 74 distribution tests passed (239 Python), plus 27 Node tests.
  Real H.265 and AV1 MP4s also passed ffprobe checks at 720p/30 fps: yuv420p, BT.709/tv, AAC,
  matching durations, 60 frames for two seconds; HEVC has the hvc1 MP4 tag.
  Nine additional three-second 1080p synthetic renders compared p4/CQ18, p4/CQ22 and p5/CQ18 for all
  three NVENC encoders. p4/CQ18 is retained for each: 1.167 / 1.069 / 1.074 seconds respectively,
  450723 / 497240 / 497370 bytes, decoded-frame RGB PSNR 39.400 / 39.414 / 39.451 dB.
  CQ22 saved bytes with lower PSNR; p5 showed no consistent meaningful benefit on this tiny fixture.
  These single-run measurements include rendering, are affected by colour conversion and are not
  a perceptual score or general benchmark. The mathematical source tone was unchanged by SHA-256.
  A fixed key captured from pre-codec code proves unchanged H.264 caching; a ready-video and timing
  regression also checks legacy records. Other-codec keys differ and timing estimates stay separate.
  Settings/volume/chapter were viewed with invented data in a 1366-pixel browser viewport; Back follows
  the logical parent and works with Enter. Audio/Video alignment and Georgia were checked in the DOM.
  Existing README screenshots have not been replaced as part of this codec update.
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
  and 8 Node tests. Current source regression totals are listed above.
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
- The dedicated `Data/State/desktop` directory is excluded from public source and payload; uninstall removes it
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

## Reading-voice rules and volume management (2026-10-22)

The actual speaker is preserved separately from the reading voice. Global, chapter and text-bound line overrides use one resolver; character references do not chain. Rule edits are previewed, revalidated and journalled using the existing project transaction mechanism, with protected Undo. Splitting/re-analysis flags stale line overrides. Project archives preserve the optional voice-rule metadata.

Eleven additional synthetic tests cover precedence, restoration of own voice, non-chaining references, stale previews, Undo conflicts, byte restoration, cache reuse, speech tags, archive round trips, cast counts, volume relinking/removal and busy-queue refusal. Browser checks on an isolated synthetic workspace exercised line preview/apply/Undo and volume folder editing. No Qwen/Gemma inference or real-owner installation/import was performed for this change. Actual own/narrator audition quality remains for the user's listening test.

Volume Edit relinks the source folder and retains the stable volume name. Remove forgets the library entry without deleting files.

## Readability and separate spoken text (2026-10-22)

Cast uses native collapsed disclosures, changed/unchanged groups, usage sorting and a nested unused group. Characters retains the existing field identities under folded detection and creation sections, with focusable, described help and Escape dismissal. Back occupies 50% of window height, with 30% resting opacity, full opacity on focus/hover and reduced-motion support.

Spoken edits are independent of source rows. Preview performs no writes; saving revalidates the script and uses the existing durable transaction journal. Restoring the original recovers the original passage keys. Splitting, re-analysis, speaker changes and manual re-preparation retain stale edits for review. Both multi-voice and single-voice rendering use saved spoken versions. No emotion classifier or automatic punctuation rewrite is claimed. The optional cleanup only adjusts punctuation spacing and duplicate !/? in dialogue after user review.

No real-model synthesis, owner installation/import, private manuscript access or publication was performed for this change. Audible prosody remains to be checked by the owner. Per-character temperature remains a plan, not an implemented setting.


## Character registry and categories (2026-10-22)

Verified with invented chapters: legacy defaults, explicit own-voice preservation, category inheritance, line/chapter precedence, volume membership and reuse of known identities, scoped aliases and scene contexts, review gating, staged JSON import, stale previews, merge transactions, project archive round trips, and video-only label invalidation. Browser checks cover category creation/reorder, moving a character, preview/apply, select-all followed by deselect-all, Voice studio navigation, and unsaved-change protection. At a 1000-pixel window the table scrolls within its container without overflowing the document. Georgia and the existing warm palette are preserved.

The expanded Gemma request and category suggestions are tested structurally; no real-model analysis or synthesis was run for this feature. Multi-volume attribution quality, long-session performance, drag-and-drop across all Windows/DPI configurations, and interrupted native desktop sessions remain unverified. The owner installation and manuscripts were not modified.

## Volume membership, narrative contexts and chapter review (2026-10-23)

Stable volume IDs survive relinking and renaming. Legacy single-volume scopes migrate once to explicit membership; a scoped alias is not widened to other volumes. Narrative contexts bind reviewed scene ranges with a source hash; stale bindings are ignored. Alias resolution and the Gemma payload are context-aware, and an alias outside its context is left Unassigned. Approval, category moves, ordering, membership, contexts and labels are separated from audio: approval alone changes no passage key, category moves freeze the old effective reading voice, and renaming updates script and audio-metadata roles without changing passage keys. Contextual video labels affect video fingerprints only. Quick view adds volume filtering and a Volumes column; the row Actions menu is a floating menu like the category menu, with keyboard, Escape and outside-click handling; drag reordering is disabled while a filter hides rows. The chapter page separates line review from character approval, allows chapter-local replacement, and links to full details.

Verified with invented projects: 233 application and 97 distribution Python tests, plus 48 Node tests, including volume-ID round trips, scope migration, scene bindings, scoped aliases, category-move voice preservation, approval without audio change, rename metadata, Quick view and drag behavior, and real Chromium checks at 1000×730 and 1440×900. README screenshots use the invented demo project.

Not verified: real Gemma or Qwen accuracy, a clean Windows installation, Volume II manuscripts, other GPUs, and owner data migration. No owner manuscript, voice or installation was used for this change.
