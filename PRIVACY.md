# Privacy and local storage

AudioBook Studio runs its web interface, TTS engine and dialogue model locally, bound to loopback.
It has no telemetry, sign-in, online TTS endpoint or automatic upload of text or audio.

During setup, the installer contacts GitHub for portable Python, FFmpeg and Ollama, PyPI for the pinned
Python wheels, Hugging Face for Qwen models, and the Ollama registry for Gemma blobs. These providers
receive normal download request information such as an IP address. Manual model import avoids those
model downloads; the other software still downloads. Vendor tools may make their own network requests.
The application is designed to use local model inference, not cloud services.

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
