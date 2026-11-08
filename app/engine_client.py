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
from voices import BASE_CLONE, CLONE_TIMBRE, MODEL_FILES, VOX_CLONE, voice_parameters

from project import LAYOUT
ROOT = LAYOUT.program
BUILD = ROOT / "engine" / "build"
CUDA = ROOT / "engine" / "cuda"
BASE_URL = "http://127.0.0.1:7864"
# The optional VoxCPM2 engine runs in its own Python (PyTorch), on its own port. Only one engine holds the GPU.
VOXCPM_URL = "http://127.0.0.1:7865"
VOXCPM_CONFIG = LAYOUT.state / "voxcpm.json"
CODEC = LAYOUT.models / model_profile.CURRENT["codec"]
LOG = LAYOUT.state / 'logs/engine.log' if LAYOUT.installed else ROOT/'engine.log'
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


def _stop_orphan(port, executable):
    """An engine left by an earlier crash of this app (same executable) is stopped; anything else on the
    port is reported, never killed."""
    import psutil
    for connection in psutil.net_connections("tcp"):
        if connection.laddr and connection.laddr.port == port and connection.status == psutil.CONN_LISTEN:
            try:
                process = psutil.Process(connection.pid)
                if Path(process.exe()).resolve() == Path(executable).resolve():
                    process.kill()
                    process.wait(10)
                    return
            except (psutil.Error, OSError):
                pass
            raise RuntimeError(f"Port {port} is being used by another program. Close the other speech engine.")


def voxcpm_runtime():
    """{"python", "model"} of the optional VoxCPM2 engine, from voxcpm.json in the state folder, or None when it
    is not installed. Both paths must exist: a half-removed runtime is reported as missing, not started."""
    try:
        data = json.loads(VOXCPM_CONFIG.read_text(encoding="utf-8"))
        runtime = {"python": Path(data["python"]), "model": Path(data["model"])}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not runtime["python"].is_file() or not (runtime["model"] / "model.safetensors").is_file():
        return None
    return runtime


def _url(mode):
    return VOXCPM_URL if mode == VOX_CLONE else BASE_URL


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


def _launch(mode):
    """(command, working folder, extra PATH, port, seconds to load) of the engine serving `mode`."""
    if mode == VOX_CLONE:
        runtime = voxcpm_runtime()
        if runtime is None:
            raise FileNotFoundError("The VoxCPM2 engine is not installed. Choose Qwen as the narrator's engine.")
        server = Path(__file__).with_name("voxcpm_server.py")
        command = [str(runtime["python"]), str(server), "--model", str(runtime["model"]), "--port", "7865"]
        return command, ROOT, "", 7865, 300
    if mode not in MODEL_FILES:
        raise ValueError("Unknown Qwen model.")
    model = LAYOUT.models / MODEL_FILES[mode]
    for path in (model, CODEC, BUILD / "tts-server.exe"):
        if not path.is_file():
            raise FileNotFoundError(f"Required file is missing: {path}")
    command = [str(BUILD / "tts-server.exe"), "--model", str(model), "--codec", str(CODEC),
               "--device", "CUDA0", "--host", "127.0.0.1", "--port", "7864",
               "--lang", "English", "--alias", model.stem, "--max-batch", str(MAX_BATCH)]
    return command, BUILD, str(CUDA) + os.pathsep + str(BUILD) + os.pathsep, 7864, 120


def ensure_engine(mode):
    """Start the engine serving `mode`, closing the other one first: Qwen and VoxCPM2 never share the GPU."""
    global _process, _log_handle, _current_model
    name = "VoxCPM2" if mode == VOX_CLONE else "Qwen"
    command, folder, path, port, seconds = _launch(mode)
    if _process is not None:
        if _current_model == mode and _process.poll() is None:
            return
        if _current_model == mode:
            raise RuntimeError(f"The {name} engine stopped.\n" + log_tail())
        close_engine()
    with socket.socket() as connection:
        connection.settimeout(1)
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            _stop_orphan(port, command[0])
    env = os.environ.copy()
    env["PATH"] = path + env["PATH"]
    _log_handle = LOG.open("w", encoding="utf-8")
    _process = subprocess.Popen(
        command, cwd=folder, env=env, stdout=_log_handle, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _kill_with_parent(_process)
    _current_model = mode
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _process.poll() is not None:
            raise RuntimeError(f"The {name} engine did not start.\n" + log_tail())
        try:
            with urlopen(_url(mode) + "/health", timeout=1) as response:
                if response.status == 200:
                    return
        except URLError:
            pass  # The child is still loading models, so its HTTP port is not ready.
        time.sleep(0.5)
    close_engine()
    raise TimeoutError(f"The model did not load within {seconds} seconds. See engine.log.")


def _register(voice_id, mode=BASE_CLONE):
    """Give the running engine the approved take (audio + exact text) behind a fixed voice, once per engine."""
    import base64
    import fixed_voices
    if voice_id in _registered:
        return
    wav, text = fixed_voices.reference(voice_id)
    body = {"name": voice_id, "ref_text": text, "wav_b64": base64.b64encode(wav.read_bytes()).decode("ascii")}
    request = Request(_url(mode) + "/v1/audio/voices", data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=120):
            pass
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"The engine rejected the fixed voice ({error.code}): {detail}") from error
    _registered.add(voice_id)


def request_body(text, mode, voice, instruction, seed, temperature):
    """The speech request for the engine serving `mode`. VoxCPM2 takes the delivery as a style hint and has no
    temperature; Base takes no delivery (it comes from the reference take)."""
    if mode == VOX_CLONE:
        return {"input": text, "voice": voice, "style": instruction, "seed": int(seed)}
    payload = {
        "input": text, "language": "English", "response_format": "wav",
        "seed": int(seed), "temperature": float(temperature), "max_new_tokens": 2048,
    }
    if instruction:
        payload["instructions"] = instruction
    if mode == BASE_CLONE:
        payload["subtalker_temperature"] = CLONE_TIMBRE
    if voice:
        payload["voice"] = voice
    return payload


def synthesize(text, mode, speaker, description, instructions, seed, temperature):
    voice, instruction = voice_parameters(mode, speaker, description, instructions)
    ensure_engine(mode)
    if mode in (BASE_CLONE, VOX_CLONE):
        _register(voice, mode)
    payload = request_body(text, mode, voice, instruction, seed, temperature)
    name = "VoxCPM2" if mode == VOX_CLONE else "Qwen"
    request = Request(_url(mode) + "/v1/audio/speech", data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=600) as response:
            return response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{name} generation failed ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError(f"The connection to the {name} engine was interrupted.\n" + log_tail()) from error
