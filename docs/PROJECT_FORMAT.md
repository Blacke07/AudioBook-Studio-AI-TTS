# AudioBook Studio project format, version 1

An `.abstudio` file is a ZIP archive. It is data, never a plugin or executable. Processing stays local.
`project.json` contains `format: "audiobook-studio-project"`, integer `version: 1`, `app_version`, `created`,
`parts` and an optional `note`. Parts are `settings`, `cast` and `volumes`; each is optional.

| Entry | Part | Contents |
| --- | --- | --- |
| `settings.json` | settings | Narrator, reading, audio export and optional video settings |
| `characters.json` | cast | Native version 2 character records, including aliases, model, description and seed |
| `voices/registry.json` | cast | Fixed voice IDs, filenames, reference transcripts and provenance |
| `voices/samples.json` | cast | Audition text and optional serious comparison text |
| `voices/<filename>.wav` | cast | Only WAV files referenced by the registry |
| `volumes.json` | volumes | Volume names and source folder paths; original chapter files are not embedded |
| `scripts/<volume>/<chapter>/script.json` | volumes | Speaker assignments and their source hashes |

Speaker assignments **contain the book text**. Export warns against sharing them publicly. Cast-only
exports omit scripts, source paths and the `real` book-example field in audition samples. They still
contain voice notes, reference audio and exact reference transcripts; review those before sharing.
No generated chapter audio, passage cache, video, model, runtime or original manuscript is exported.

Import shows a read-only preview. Settings require explicit selection. Existing characters, fixed voices
and scripts default to Keep mine; individual conflicts can use the imported record instead. Existing
volume folders are kept unless explicitly relocated. Missing absolute local drive paths remain registered
with a warning. New volumes with UNC, device, relative or other non-local source syntax are skipped and
never saved; Locate folder supplies a valid absolute local drive path instead. Existing unsafe volume
paths are also refused before filesystem probing when the Volumes page reads them.

Scripts require a matching chapter and `source_hash`, plus matching normalized text: the concatenated
row text must equal the local chapter's `dialogue.segment()` text, ignoring whitespace only. Changed
words, punctuation, reordered, missing or extra text are refused even if the package copies a valid hash. Unknown
speakers, changed text, missing or ambiguous chapters are reported as skipped. Existing scripts require
an explicit replacement choice. Text inside script rows is never translated or rewritten.

Fixed voice ID is `fix-` plus the first 10 hex digits of SHA-1(WAV bytes + exact UTF-8 transcript), as in
the application's fixed-voice implementation. WAVs must decode completely, contain finite samples,
be mono/stereo at 8–48 kHz and last 4–300 seconds. Filenames cannot replace a different existing WAV.

Limits: 10,000 archive entries; 1 GiB total expanded bytes; 32 MiB per JSON/unknown entry; 64 MiB per WAV.
All archive entries, including ignored ones, count toward the limits. Absolute paths, drive names,
backslashes, traversal, symlinks, encrypted entries and duplicate/case-colliding names are refused.
Only the entries above are read; other safe names are ignored and reported. JSON duplicate keys and
nonfinite numbers are refused. Future format versions are refused; unknown object fields are ignored.
Volume/chapter/WAV names use the application's filename rules, with Windows device-name and
case-collision checks. Speaker display names instead share the glossary validator: 1–1024 characters,
no control characters, reserved system roles or names duplicated ignoring letter case. Punctuation,
slashes and quotes in display names are permitted; these names never become archive paths.

Before applying, the archive digest, project state and source-folder results must still match the preview.
The queue must be idle and is reserved while transfer data is processed, without holding the worker's
status lock. Native dialogs hold no project gate or worker reservation; queue state is rechecked after
they close. API reads and auditions may run concurrently; project-changing calls and import/Undo acquire
exclusive access so readers cannot observe a half-applied import. A waiting writer precedes new readers.
All new files and preimages are staged under `projects-state/transaction`; a persistent journal restores
preimages after an error or an interrupted process, before the next server starts serving requests.
An unresolved recovery error prevents startup rather than hiding a partial import.

Automatic backups are stored in `projects-backup/<timestamp>-<id>.abstudio`. They contain the full private
project state, including book example lines. Internal `_snapshot_existing` metadata records which files
actually existed, allowing exact restoration of absent files as well as existing files. This metadata is
used only for the application's own digest-verified Undo backup, not for normal imports.

Undo restores settings, cast, volumes and assignments from before the last import and removes files
introduced by that import. It can replace later edits, so confirmation is required. A new safety backup
is saved first. Original manuscripts and generated audio/export/cache files are untouched.
Import reports are stored locally in `projects-state/reports`. Neither state, backups nor `.abstudio`
files can enter the public source or installer allowlists.

Preview tokens expire after 30 minutes and are single-use for successful application. Reopen/refresh a
preview after editing the project. Save/Open use native dialogs; there are no browser uploads and no
additional multipart dependency. Installation is a separate step.
