# Privacy and local storage

AudioBook Studio runs its web interface, TTS engine and dialogue model locally, bound to loopback.
It has no telemetry, sign-in, online TTS endpoint or automatic upload of text or audio.

During setup, the installer contacts GitHub for portable Python, FFmpeg and Ollama, PyPI for the pinned
Python wheels, Hugging Face for Qwen models, and the Ollama registry for Gemma blobs. These providers
receive normal download request information such as an IP address. Manual model import avoids those
model downloads; the other software still downloads. Vendor tools may make their own network requests.
The application is designed to use local model inference, not cloud services.

The desktop window uses a dedicated Microsoft WebView2 profile under `.desktop/WebView2`, separate
from your browser's profiles. It can contain local page storage, cache and history. The embedded page
is restricted to this application's loopback origin; external HTTP(S) links clicked by the user open
in the default browser. Host-object access, web messaging, password saving, autofill and permission
requests are disabled for the embedded content. The shared Microsoft runtime may make its own vendor
requests or receive updates. If it is missing, setup asks before contacting Microsoft to install it.
Uninstallation removes the dedicated `.desktop` folder, but keeps the shared WebView2 Runtime.

Manuscripts are read from folders chosen by the user. Working scripts, speaker assignments, audio caches,
settings, volume paths and fixed voice WAVs are stored in the installation folder. Logs can include local
paths and error context. Review logs before sharing them. Deleting a volume from the interface does not
delete the original manuscript. Back up source material independently.

The public release contains nine synthetic voice presets (two narrators, seven character voices), the default
narrator and generic settings. All of them are Qwen3-TTS Voice Design takes, not recordings of real people; their
reference sentences were written for the voices and are not quotations from any book. Their calibration vector was
computed from 19 separately generated synthetic samples. No manuscripts, character notes or glossary are included.
`demo-provenance.json` records the hash of every distributed voice.

The voice personality guide is a local reference document. Copying it does not send anything online.
If you paste your manuscript into another assistant, that assistant's data policy applies.

Do not expose the local server to the internet. This release has no multi-user authentication or tenant
isolation and is not intended for network hosting. The server answers only requests addressed to
`127.0.0.1`, `localhost` or `[::1]` and refuses requests sent by other web pages open in your browser.

## Project files and automatic backups

Project export saves only the parts you select, to an `.abstudio` file chosen in a native Save dialog.
Settings, cast/fixed voices, and volumes/speaker assignments are separate choices. Speaker assignments
include the **text of the book**, even though the original TXT/DOCX files are not included. Do not share
those packages publicly. Cast-only exports omit scripts and real-book audition examples, but contain
voice notes, WAV references and exact transcripts. Review them before sharing a voice pack.

Import preview does not write any project files. Applying an import creates a private backup under
`projects-backup`; import reports and recovery journals live under `projects-state`. Backups contain
settings, voices, source folder paths and saved script text and should be kept private. Undo can replace
later edits and first creates another safety backup. Generated chapter audio, exports, caches, models
and original manuscript files are not moved or deleted by project import/Undo.

These operations stay local; no project is sent to GitHub or another service. Native Open/Save dialogs
are used instead of browser file uploads. Local preview paths and conflict details can be visible in
screenshots, so review screenshots before sharing. See [the project format](docs/PROJECT_FORMAT.md).
