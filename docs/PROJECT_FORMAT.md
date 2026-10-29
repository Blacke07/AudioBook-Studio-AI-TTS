# AudioBook Studio project format, version 1

An `.abstudio` file is a ZIP archive. It is data, never a plugin or executable. Processing stays local.
`project.json` contains `format: "audiobook-studio-project"`, integer `version: 1`, `app_version`, `created`,
`parts` and an optional `note`. Parts are `settings`, `cast` and `volumes`; each is optional.

| Entry | Part | Contents |
| --- | --- | --- |
| `settings.json` | settings | Narrator, reading, audio export and optional video settings |
| `characters.json` | cast | Version 3 character identities and shared voices, with aliases and voice recipes; supported older records are converted on import |
| `voices/registry.json` | cast | Fixed voice IDs, filenames, reference transcripts and provenance |
| `voices/samples.json` | cast | Audition text and optional serious comparison text |
| `voices/<filename>.wav` | cast | Only WAV files referenced by the registry |
| `volumes.json` | volumes | Volume IDs, display names and source folder paths; original chapter files are not embedded. Exported packages keep the stable volume ID on import. |
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

Automatic backups are stored in `Backups/Projects/<timestamp>-<id>.abstudio` in an installation
(`projects-backup` in a development checkout). They contain the full private
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

## Reading-voice metadata

A character may contain `read_as` naming Narrator or another existing character. Absent inherits its category policy, then own voice for legacy data. A script may contain `voice_rules.characters` (chapter exceptions), `voice_rules.lines` (row, speaker, text_hash, source_hash, read_as), and `voice_rules.conflicts` (stale overrides requiring review). Line text hashes use SHA-256 of the JSON-encoded text; source_hash retains the existing chapter hash. Targets use their own voices; rules never chain. Import keeps existing character rules unless that character is explicitly replaced. These optional fields do not change the archive container version.

## Spoken-text overrides

Scripts may contain `spoken_text.lines` entries with `row`, `speaker`, `text_hash`, `source_hash` and `text`. The original `rows` remain byte-for-byte unchanged at the string level. Hashes bind each edit to its original text, speaker and chapter source; `text_hash` uses the same JSON/SHA-256 digest as line voice rules. Stale entries move to `spoken_text.conflicts` and require explicit review. The original-source comparison on import is unchanged; overrides are validated separately. Exports containing assignments also contain these spoken versions and must remain private when they contain book text.


## Character registry

Version 2 glossaries may include an optional `organization` object alongside `characters`:

- `categories`: ordered records with stable `id`, display `name`, `description`, and `voice` (`own`, `Narrator`, or an existing character reference). `uncategorized` must remain present. Array order is presentation priority; it never decides who speaks.
- `characters`: metadata keyed by stable character identity: `category`, `status` (`approved`, `provisional`, `needs_review`), video `label`, evidence `reason`, optional `volumes` (stable volume IDs), optional `contexts` (narrative-context IDs), optional `alias_scopes` (alias to `volumes`/`contexts` where it is valid), and optional `labels` (context-specific video labels).
- `contexts`: optional narrative contexts with stable `id`, `name`, `volume` (ID) and `description`, plus reviewed `scenes` bindings (`chapter`, `first`, `last`, `source_hash`). Bindings made for different chapter text are stale and are not applied.

A context may instead define `chapter_range`: `from` (inclusive) and/or `before` (exclusive), using chapter
file stems in the same natural order as the volume. Name tags use these contexts to scope both an alias and,
optionally, its display label. The canonical character and voice remain unchanged. These ranges apply to every
scene in the matching chapters; they are edited through Name tags, separately from scene bindings. Package
imports preserve the range and remap its volume/context references. Renamed boundary chapters need their rules
reviewed; range rules do not rewrite existing speaker assignments or source text.
- `allow_provisional`: explicit permission to render provisional identities; false by default. It never resolves an Unassigned speaker or permits Needs review identities.

Absent fields preserve legacy behavior. The migration gives each volume a stable ID and converts the legacy single-volume `scope` to explicit `volumes` membership once; it never widens a scoped alias to every volume. An alias claimed by two identities in the same volume or context stays unresolved. Analysis reuses an existing identity and records the volume where it speaks; it does not create a second identity because a volume was not yet listed.

Changing category order, descriptions, membership, contexts, aliases or approval does not change passage keys. Moving a character between categories keeps the effective reading voice by materializing the previous target as an explicit `read_as` when inheritance would change. Renaming rewrites assignments and the `role` fields of existing audio metadata in one transaction; passage keys stay unchanged, so unchanged audio remains valid. Video labels, including context-specific labels, affect video fingerprints only. Inherited category voices require a fixed reference; explicit chapter and line choices remain higher priority.

JSON imports are validated and staged, keep existing identities, drop foreign volume/context IDs, and mark new characters for reference review because JSON contains no WAV recordings. Project packages preserve organization metadata and fixed recordings, keeping the receiving installation's provisional-reading permission. Merge rewrites speaker references transactionally, refuses conflicting chapter policies, merges alias scopes, keeps the target voice, and leaves old reference WAVs on disk. Only active references are included in subsequent exports.
