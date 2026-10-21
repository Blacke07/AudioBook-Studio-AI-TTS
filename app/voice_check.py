"""Compare voices using centered speaker embeddings from the Base model's encoder.

The bundled calibration mean was generated from separate synthetic public samples. Scores are
heuristics for review, not guarantees of perceptual identity. The encoder runs on CPU to leave
video memory available for speech generation. Calibration provenance is documented in the release.
"""
import os
import subprocess
from threading import Lock

import numpy as np

import model_profile
from project import ROOT

TOOL = ROOT / "engine" / "build" / "spk-batch.exe"
BASE = ROOT / "models" / model_profile.CURRENT["base"]
CUDA = ROOT / "engine" / "cuda"
MEAN = ROOT / "assets" / "voice_mean.npy"
MIN_SECONDS = 1.2   # shorter clips ("Yes.") give unreliable fingerprints
# A take is "drifting" when another voice of the chapter is this close to it, relative to its own voice.
MIN_MARGIN = 0.08
CONFUSABLE = 0.5    # two fixed voices this similar can be mistaken for each other
_process = None
_lock = Lock()
_cache = {}


def available():
    return TOOL.is_file() and BASE.is_file() and MEAN.is_file()


def _start():
    global _process
    env = os.environ.copy()  # the ggml DLLs load the CUDA runtime even on the CPU device
    env["PATH"] = str(CUDA) + os.pathsep + str(TOOL.parent) + os.pathsep + env["PATH"]
    _process = subprocess.Popen([str(TOOL), "--talker", str(BASE), "--device", "CPU"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=TOOL.parent,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    ready = _process.stdout.readline().decode("utf-8", "replace")
    if not ready.startswith("READY"):
        raise RuntimeError("Voice fingerprint verification did not start.")


def embedding(path):
    """Unit-length raw speaker embedding of a WAV (cached), or None when too short to judge."""
    key = (str(path), path.stat().st_mtime)
    if key in _cache:
        return _cache[key]
    with _lock:
        if _process is None or _process.poll() is not None:
            _start()
        _process.stdin.write((str(path) + "\n").encode("utf-8"))
        _process.stdin.flush()
        answer = _process.stdout.readline().decode("utf-8", "replace").split()
    if not answer or answer[0] != "OK":
        return None  # too short or unreadable: no reliable fingerprint
    vector = np.array([float(value) for value in answer[2:]], dtype=np.float32)
    vector /= np.linalg.norm(vector) or 1.0
    _cache[key] = vector
    return vector


def similarity(a, b):
    """Raw cosine similarity of two WAVs, or None when one of them is too short to judge."""
    first, second = embedding(a), embedding(b)
    return None if first is None or second is None else float(np.dot(first, second))


def fingerprint(path):
    """Embedding with the shared component removed (see the module note), unit length."""
    vector = embedding(path)
    if vector is None:
        return vector
    if not MEAN.is_file():
        raise RuntimeError('Voice calibration data is missing. Run Verify Installation.cmd.')
    vector = vector - np.load(MEAN)
    return vector / (np.linalg.norm(vector) or 1.0)


def closeness(a, b):
    """Similarity on the centered scale: 1 = same voice, about 0 = unrelated."""
    first, second = fingerprint(a), fingerprint(b)
    return None if first is None or second is None else float(np.dot(first, second))


# Median pitch a take may have for the character's gender. Measured 21.10.2026: descriptions without an
# explicit "a woman"/"a man" ("a low, slightly husky alto") produced male voices around 100 Hz.
PITCH_RANGE = {"male": (70, 150), "female": (150, 290)}


def pitch_fits(path, gender):
    """True when the median pitch of the take suits the gender (unknown gender: always)."""
    if gender not in PITCH_RANGE:
        return True
    import librosa
    import soundfile as sf
    audio, rate = sf.read(path, dtype="float32")
    f0, voiced, _ = librosa.pyin(audio, fmin=60, fmax=400, sr=rate, frame_length=1024)
    f0 = f0[voiced & np.isfinite(f0)]
    low, high = PITCH_RANGE[gender]
    return f0.size > 5 and low <= float(np.median(f0)) <= high


def judge(take, own_reference, other_references):
    """(own, closest other name, closest other score, margin) for a generated passage."""
    mine = fingerprint(take)
    if mine is None:
        return None
    own = float(np.dot(mine, fingerprint(own_reference)))
    others = [(float(np.dot(mine, fingerprint(path))), name) for name, path in other_references.items()]
    best, name = max(others) if others else (-1.0, "")
    return {"own": round(own, 3), "other": name, "other_score": round(best, 3), "margin": round(own - best, 3)}


def close():
    global _process
    if _process is not None and _process.poll() is None:
        _process.stdin.close()
        _process.wait(10)
    _process = None
