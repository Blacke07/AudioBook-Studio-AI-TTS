"""A local VoxCPM2 speech server with the same request shape as the Qwen engine, for one fixed voice at a time.

Runs under the VoxCPM2 runtime's own Python (PyTorch + voxcpm), never under the application's, so it imports
nothing from the application. The reference take gives the timbre; a short style hint in parentheses gives the
delivery (VoxCPM2 "controllable cloning"). Audio is returned at the application's 24 kHz, 16-bit mono.

  GET  /health
  POST /v1/audio/voices   {"name", "wav_b64"}                    keep a reference take under `name`
  POST /v1/audio/speech   {"input", "voice", "style"?, "seed"}   WAV bytes
"""
import argparse
import base64
import io
import json
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RATE = 24000
CFG = 2.0
STEPS = 10


def styled(text, style):
    """VoxCPM2 reads a leading parenthesis as a style hint, not as words; one in the text itself would be
    taken for one too, so the text's own parentheses become commas."""
    text = " ".join(str(text).replace("(", ", ").replace(")", ", ").split())
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",(\s*,)+", ",", text).strip(" ,")
    style = " ".join(str(style or "").replace("(", " ").replace(")", " ").split())
    return f"({style}){text}" if style else text


class Engine:
    def __init__(self, model_path):
        import torch
        from voxcpm import VoxCPM
        self.torch = torch
        self.model = VoxCPM.from_pretrained(model_path, load_denoiser=False)
        self.voices = {}
        self.folder = Path(tempfile.mkdtemp(prefix="voxcpm-voices-"))
        self.lock = threading.Lock()

    def register(self, name, wav):
        path = self.folder / f"{len(self.voices)}.wav"
        path.write_bytes(wav)
        self.voices[name] = path

    def speak(self, text, voice, style, seed):
        import soundfile as sf
        import torchaudio.functional as F
        if voice not in self.voices:
            raise KeyError(f"Unknown voice {voice}.")
        with self.lock:
            self.torch.manual_seed(seed)
            self.torch.cuda.manual_seed_all(seed)
            wav = self.model.generate(text=styled(text, style), reference_wav_path=str(self.voices[voice]),
                                      cfg_value=CFG, inference_timesteps=STEPS)
        audio = self.torch.from_numpy(wav).float()
        audio = F.resample(audio, self.model.tts_model.sample_rate, RATE).clamp(-1, 1).numpy()
        buffer = io.BytesIO()
        sf.write(buffer, audio, RATE, subtype="PCM_16", format="WAV")
        return buffer.getvalue()


def handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, body, kind="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message):
            self._reply(status, json.dumps({"error": message}).encode("utf-8"))

        def do_GET(self):
            if self.path == "/health":
                self._reply(200, b'{"ok": true}')
            else:
                self._error(404, "Not found.")

        def do_POST(self):
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path == "/v1/audio/voices":
                    engine.register(str(data["name"]), base64.b64decode(data["wav_b64"]))
                    self._reply(200, b'{"ok": true}')
                elif self.path == "/v1/audio/speech":
                    wav = engine.speak(data["input"], str(data["voice"]), data.get("style", ""), int(data.get("seed", 0)))
                    self._reply(200, wav, "audio/wav")
                else:
                    self._error(404, "Not found.")
            except (KeyError, ValueError, TypeError) as error:
                self._error(400, str(error))
            except Exception as error:  # the log keeps the details; the application shows the message
                self._error(500, f"{type(error).__name__}: {error}")

        def log_message(self, format, *args):
            print(format % args, flush=True)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, default=7865)
    args = parser.parse_args()
    engine = Engine(args.model)
    print("VoxCPM2 ready", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler(engine)).serve_forever()


if __name__ == "__main__":
    main()
