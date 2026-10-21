"""Own one local CUDA GGUF server and send speech requests to it."""
import atexit
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import model_profile
from voices import BASE_CLONE, CLONE_TIMBRE, MODEL_FILES, voice_parameters

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "engine" / "build"
CUDA = ROOT / "engine" / "cuda"
BASE_URL = "http://127.0.0.1:7864"
CODEC = ROOT / "models" / model_profile.CURRENT["codec"]
LOG = ROOT / "engine.log"
# Concurrent passages on the GPU. Measured 20.10.2026 on 8 passages: batch 1 RTF 0.42, batch 4 RTF 1.55
# (slower) and different audio for the same seed, so passages are generated one at a time.
MAX_BATCH = 1
_process = None
_log_handle = None
_current_model = None
_job = None


def _kill_with_parent(process):
    """Put the engine in a Windows job object closed with this process, so closing the launcher window
    can never leave an orphan server holding the GPU and the port."""
    global _job
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.OpenProcess.restype = wintypes.HANDLE
    if _job is None:
        _job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel.SetInformationJobObject(wintypes.HANDLE(_job), 9, ctypes.byref(info), ctypes.sizeof(info))
    handle = kernel.OpenProcess(0x0001 | 0x0100, False, process.pid)  # PROCESS_TERMINATE | SET_QUOTA
    kernel.AssignProcessToJobObject(wintypes.HANDLE(_job), wintypes.HANDLE(handle))
    kernel.CloseHandle(wintypes.HANDLE(handle))


def _stop_orphan():
    """An engine left by an earlier crash of this app (same executable) is stopped; anything else on the
    port is reported, never killed."""
    import psutil
    for connection in psutil.net_connections("tcp"):
        if connection.laddr and connection.laddr.port == 7864 and connection.status == psutil.CONN_LISTEN:
            try:
                process = psutil.Process(connection.pid)
                if Path(process.exe()).resolve() == (BUILD / "tts-server.exe").resolve():
                    process.kill()
                    process.wait(10)
                    return
            except (psutil.Error, OSError):
                pass
            raise RuntimeError("Port 7864 is being used by another program. Close the other Qwen instance.")


_registered = set()  # fixed voices known to the running Base engine


def close_engine():
    global _process, _log_handle, _current_model
    _registered.clear()
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait()
    _process = None
    _current_model = None
    if _log_handle is not None:
        _log_handle.close()
        _log_handle = None


atexit.register(close_engine)


def log_tail():
    if not LOG.exists():
        return ""
    with LOG.open("rb") as stream:
        stream.seek(max(0, LOG.stat().st_size - 2500))
        return stream.read().decode("utf-8", errors="replace")


def ensure_engine(mode):
    global _process, _log_handle, _current_model
    if mode not in MODEL_FILES:
        raise ValueError("Unknown Qwen model.")
    model = ROOT / "models" / MODEL_FILES[mode]
    for path in (model, CODEC, BUILD / "tts-server.exe"):
        if not path.is_file():
            raise FileNotFoundError(f"Required file is missing: {path}")
    if _process is not None:
        if _current_model == mode and _process.poll() is None:
            return
        if _current_model == mode:
            raise RuntimeError("The Qwen engine stopped.\n" + log_tail())
        close_engine()
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(("127.0.0.1", 7864)) == 0:
            _stop_orphan()
    env = os.environ.copy()
    env["PATH"] = str(CUDA) + os.pathsep + str(BUILD) + os.pathsep + env["PATH"]
    _log_handle = LOG.open("w", encoding="utf-8")
    _process = subprocess.Popen(
        [str(BUILD / "tts-server.exe"), "--model", str(model), "--codec", str(CODEC),
         "--device", "CUDA0", "--host", "127.0.0.1", "--port", "7864",
         "--lang", "English", "--alias", model.stem, "--max-batch", str(MAX_BATCH)],
        cwd=BUILD, env=env, stdout=_log_handle, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _kill_with_parent(_process)
    _current_model = mode
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if _process.poll() is not None:
            raise RuntimeError("The Qwen engine did not start.\n" + log_tail())
        try:
            with urlopen(BASE_URL + "/health", timeout=1) as response:
                if response.status == 200:
                    return
        except URLError:
            pass  # The child is still loading models, so its HTTP port is not ready.
        time.sleep(0.5)
    close_engine()
    raise TimeoutError("The model did not load within 120 seconds. See engine.log.")


def _register(voice_id):
    """Give the Base engine the approved take (audio + exact text) behind a fixed voice, once per engine."""
    import base64
    import fixed_voices
    if voice_id in _registered:
        return
    wav, text = fixed_voices.reference(voice_id)
    body = {"name": voice_id, "ref_text": text, "wav_b64": base64.b64encode(wav.read_bytes()).decode("ascii")}
    request = Request(BASE_URL + "/v1/audio/voices", data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=120):
            pass
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"The engine rejected the fixed voice ({error.code}): {detail}") from error
    _registered.add(voice_id)


def synthesize(text, mode, speaker, description, instructions, seed, temperature):
    voice, instruction = voice_parameters(mode, speaker, description, instructions)
    ensure_engine(mode)
    if mode == BASE_CLONE:
        _register(voice)
    payload = {
        "input": text, "language": "English", "response_format": "wav",
        "seed": int(seed), "temperature": float(temperature), "max_new_tokens": 2048,
    }
    if instruction:  # Base takes none: its delivery comes from the reference take
        payload["instructions"] = instruction
    if mode == BASE_CLONE:
        payload["subtalker_temperature"] = CLONE_TIMBRE
    if voice:
        payload["voice"] = voice
    request = Request(BASE_URL + "/v1/audio/speech", data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=600) as response:
            return response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Qwen generation failed ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError("The connection to the Qwen engine was interrupted.\n" + log_tail()) from error
