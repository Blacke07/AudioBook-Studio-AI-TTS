# AudioBook Studio

[![Buy me a coffee](https://img.shields.io/badge/Buy_me_a_coffee-D97745?style=for-the-badge&logo=buymeacoffee&logoColor=white)](https://buymeacoffee.com/4reign)

Turn English TXT or DOCX chapters into an audiobook on your Windows computer. Use a narrator, fixed character voices, and optional videos with synchronized reading text.

**[Download the current installer](https://github.com/Blacke07/AudioBook-Studio-AI-TTS/releases/download/current/AudioBookStudio-Setup.exe)** · [All downloads](https://github.com/Blacke07/AudioBook-Studio-AI-TTS/releases/latest) · [Report a problem](https://github.com/Blacke07/AudioBook-Studio-AI-TTS/issues)

Your manuscripts are read without being modified. Speaker analysis and voice generation run locally. Internet access is needed to download installation components and models; no online voice account is required.

## What is included

- A desktop window with its own launcher, shortcuts, remembered window position, and confirmation before stopping active work.
- Local speaker attribution with Gemma and speech generation with Qwen3-TTS.
- Two ready-made narrators and seven synthetic character voices, plus Voice Design and built-in speaker auditions.
- A character registry with categories, reading-voice policies, provisional identities, and quick editing.
- A chapter editor for manual speaker assignments, reading-voice overrides, and separate spoken-text edits.
- Chapter audio, whole-volume audiobook export, optional MP4 reading videos, and YouTube chapter timestamps.
- Project import/export with a preview, conflict choices, automatic import backups, and Undo.

## Install

1. Download **AudioBookStudio-Setup.exe** from the current release.
2. Put it in an empty local folder, such as `D:\AudioBook Studio`. Setup installs into that folder. A recognized existing installation can also be updated after closing the app; unknown nonempty folders are refused.
3. Choose **Standard** or **Compact**, then choose automatic model downloads or supply your own model files.
4. Click **Install**. When setup finishes, choose **Open AudioBook Studio** and optionally create shortcuts.

Setup installs a private Python environment, pinned dependencies, the native voice engine, FFmpeg and portable Ollama. Miniconda, PyTorch and a system Python installation are not required. Downloads are checked by size and SHA-256.

Microsoft WebView2 Runtime provides the desktop window. If it is missing, setup asks before downloading and installing it. The shared runtime remains installed when AudioBook Studio is removed and receives Microsoft's own updates.

The installer is unsigned. Compare its SHA-256 with `SHA256SUMS.txt` from the same release.

### Requirements

| Component | Requirement |
| --- | --- |
| Windows | Windows 10 or 11, x64, with an AVX2-capable CPU |
| GPU | Supported NVIDIA RTX 20/30/40/50 architecture, driver 570.65 or newer |
| Standard | At least 12 GB VRAM and 40 GB free disk space |
| Compact | At least 8 GB VRAM and 25 GB free disk space; experimental |
| RAM | 32 GB recommended |

The engine includes CUDA targets 7.5, 8.0, 8.6, 8.9 and 12.0. Physical testing is limited to one RTX 4080 Laptop with 12 GB VRAM. Compiled support for other cards is not confirmation that they have been tested. Cards with less than 8 GB VRAM and other GPU vendors are not accepted by this build.

### Standard or Compact?

| | Standard | Compact — experimental |
| --- | --- | --- |
| Model downloads | About 24 GiB | About 12 GiB |
| Fixed-reference book reading | Qwen Base | The same Qwen Base model |
| Voice Design / built-in speaker models | Full precision | Q8 |
| Speaker attribution | Gemma 4 12B | Gemma 4 E4B |

Both profiles use the same model and recordings for fixed-reference reading. Compact's audition models and speaker-attribution model differ; their memory use, speed and quality have not been measured on an 8 GB card.

### Supply model files yourself

Choose **I already have the model files**, then **Create models folder**. Setup creates the final `models` folder next to the installer, with a list of exact filenames, sizes, hashes and links.

Place the four requested GGUF files directly in `models`, and the pinned Gemma blobs in `models/ollama/blobs`. Click **Check again**, then **Install**. Those files are verified and used in place, without a second staging folder or duplicate copy. Other installation components still download as needed.

## Make your first audiobook

1. **Narrator:** keep the supplied narrator, select another preset, or design and fix your own reference voice.
2. **Characters:** add the cast, organize categories, and choose which voice reads each character.
3. **Volumes:** add a folder of numbered TXT or DOCX chapters. Edit can relink its folder; Remove forgets the library entry while leaving source files and generated files on disk.
4. **Analyze Text:** review speaker assignments, newly discovered characters, and any uncertain lines. Failed analysis offers diagnosis and smaller-batch repair. Manual assignments remain available without Gemma.
5. **Audio:** generate and listen to a sample chapter before processing a full volume. Export chapters or use **Export the whole volume** for an audio audiobook file.
6. **Video, optional:** create reading videos from current audio after the previous stages are complete.

The ordered **Text → Audio → Video** workflow checks the selected batch before advancing. Completed passages can be reused after an interruption; only passages whose sound changes need new synthesis.

## Characters and reading voices

**Quick view** provides search, status filters, category assignment, reading-voice selection and quick details. Changes remain a draft until you preview and apply them. **Voice studio** contains the detailed reference, audition and voice-creation tools.

Create and reorder categories, edit their descriptions, and move characters individually or in a batch. Drag handles and menu actions provide the same organizing operations. Each category can default to own voices, the narrator, or a shared character reference. Existing fixed voices are preserved as explicit own-voice choices during the first registry migration.

The actual speaker and the reading voice are separate. A minor character may keep a descriptive name in the script and video while the narrator or a shared reference reads the dialogue.

Reading-voice priority is:

**Line override → chapter override → explicit character choice → category default → own voice.**

Another character's voice means that character's own reference; voice rules do not chain. Category priority provides organizing context, not permission to override textual evidence about who speaks. Category order and descriptions alone do not invalidate existing audio.

### New and provisional speakers

New speakers discovered during analysis are provisional and scoped to their volume. Gemma can suggest a category for a supported identity. Review the passages, correct the details, approve the character, or merge a duplicate into an established identity. Ambiguous assignments remain **Unassigned**.

**Allow provisional characters to use their assigned reading voice** is off by default. Enabling it permits supported provisional identities to use their assigned voice; it does not bypass unresolved speaker assignments or identities marked **Needs review**.

Identity renaming and video labels are separate. Changing only a video label preserves reusable audio and makes affected videos outdated. Merge keeps the target character's reference, refuses conflicting chapter policies, and retains old reference WAVs on disk.

The volume **Cast and reading voices** section folds by category, with unused characters kept separately. Open a character there, a chapter legend entry, or a line's **Voice** control to edit its reading rule. Preview the affected chapters before applying. Existing voice-rule Undo is protected against overwriting later edits.

### Edit the spoken version

Use **Edit spoken text** beside a prepared line to adjust the version sent to the voice generator. The manuscript and original script text stay unchanged. Preview before saving; **Restore original** removes the edit.

**Suggest punctuation cleanup** only adjusts dialogue punctuation spacing and repeated `!` or `?`. It does not infer emotions or rewrite sentences. Punctuation can influence delivery, but does not guarantee a particular intonation. Listen after regeneration.

Reanalysis, splitting or speaker changes retain unmatched voice/text overrides for review instead of silently applying them to another line.

## Project import and export

Use **Project** to export or import an `.abstudio` package. Select settings, characters with fixed references, or volumes with speaker assignments. Preview additions, missing folders and conflicts before applying. Existing data is kept by default; settings are opt-in. An import creates a private backup and supports **Undo last import**.

Character categories, reading policies, video labels and spoken-text overrides travel with the relevant project data. Missing chapter folders can be located during import. Assignments are refused when their text does not match the local chapter.

**Import characters** also accepts a JSON glossary. JSON imports are staged, keep existing characters and flag new entries for review. JSON contains recipes and identity facts, not fixed-reference WAV recordings; use an `.abstudio` character-and-voice package to transfer those recordings.

**Speaker assignments contain book text. Do not share those packages publicly.** Voice packs may contain reference transcriptions and notes, so review them before sharing. Original manuscripts, generated audio, model files and caches are not transferred in project packages. See [project format](docs/PROJECT_FORMAT.md).

## Optional video

Create MP4 videos from audio that is already generated and current. Videos show speaker labels, the active passage, and faded scrolling context. Automatic video is off by default.

- Use **Create video** in a chapter or **Create videos** for a volume selection.
- In **Settings and export → Video**, choose resolution, context, progress bar, footer and codec.
- Enable **Also create an MP4 video** to include video after audio export during automatic processing.
- Export YouTube chapter timestamps after creating current chapter videos. The timestamps assume chapters are joined in order without gaps.

H.264 uses NVENC when available, with CPU encoding available otherwise. H.265 and AV1 require a successful NVENC capability check; unsupported choices show a reason. Audio is reused and encoded as AAC in the MP4. Video duration is checked before publication, and incomplete output does not replace an existing completed file.

Full-volume MP4 joining is not included. **Export the whole volume** exports audio. Text synchronization is passage-level, rather than individual-word alignment.

## Files, updates and uninstall

| Location | Contents |
| --- | --- |
| `Audiobooks/<volume>` | Exported audio, videos and YouTube chapter lists |
| `Backups` | Project and migration backups |
| `models` | Qwen and Ollama model files |
| `Data/User` | Settings, characters, fixed voices, scripts and generated work |
| `Data/Program` | Replaceable program files and private dependencies |
| `Data/State` | Installer metadata, logs and desktop profile |

Run **AudioBook Studio.exe** to start the application. Closing its window checks for active or queued work. Starting the same installation again restores its existing window.

Updates recognize the existing installation and preserve user data. Unrecognized folders or conflicting destinations are refused. For another computer, export a project, install there, and preview the import. Keep manuscripts separately and locate their folders when needed; do not move an installed Python environment between folders.

To uninstall, close the app and run **Uninstall AudioBook Studio.exe**. Audiobooks, Backups, models and Data/User are retained by default. Deleting them requires separate explicit choices. Source manuscripts and unknown files are kept. See [privacy](PRIVACY.md) for local services and installation downloads.

There is one rolling release, **current**, with stable filenames. Its assets are replaced together when improvements are published. Save the matching checksum file if you keep an older download.

## Testing and limitations

This is a personal project, tested on one Windows computer with an RTX 4080 Laptop, 12 GB. The current checks passed **309 Python tests** (212 application and 97 distribution tests) and **35 Node tests**, plus targeted browser checks, public-content auditing and package integrity verification.

Those checks do not guarantee operation on every computer. Physical RTX 20/30/50 hardware, Compact on an 8 GB card, clean-Windows installation, and the missing-WebView2 installation path remain unverified. Native desktop lifecycle tests use a fake backend for several interruption scenarios.

The new character registry has automated and browser coverage, but its expanded Gemma category suggestions have not been measured with real-model runs. Large projects, drag-and-drop across Windows/DPI configurations, and long sessions need further testing. Review speaker assignments and listen before generating a whole book. See [VERIFICATION.md](VERIFICATION.md) for details.

Bug reports are welcome in [Issues](https://github.com/Blacke07/AudioBook-Studio-AI-TTS/issues). Include Windows version, GPU and reproduction steps; leave out private manuscripts and personal recordings.

## Customize and contribute

Everyone is welcome to try the build, fork it and customize it for their own workflow. Contributions and improvements are welcome. Keep the MIT license notice and respect the separate licenses of models and third-party components.

The repository contains the app, installer, tests and public synthetic voice assets. Models, downloaded dependencies, private development records and user data are excluded. Build instructions are in [docs/BUILD.md](docs/BUILD.md). Releases include the reviewed application source and exact native engine source.

## License and credits

The application's own code is [MIT-licensed](LICENSE). Third-party components retain their licenses: Qwen3-TTS and Gemma 4 (Apache-2.0), the native engine (MIT), NVIDIA CUDA terms and FFmpeg (GPL). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `licenses/`.

Use only texts and voice references you have the right to use. The application does not grant rights to source material.

<sub>Developed and tested with assistance from Opus 5.5 and GPT 6.1-Sol. Errors may remain; AI-assisted development and automated checks do not replace independent testing.</sub>
