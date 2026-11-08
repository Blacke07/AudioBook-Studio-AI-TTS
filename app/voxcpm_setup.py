"""Install, find and link the optional VoxCPM2 engine (its own Python with PyTorch, plus the model).

  <install folder>/voxcpm/venv/        a virtual environment made with the application's own Python
  <install folder>/voxcpm/model/       the VoxCPM2 weights from Hugging Face (about 5 GB)
  <state folder>/voxcpm.json           {"python", "model"}: what engine_client starts

Setting it up downloads about 8 GB (PyTorch with CUDA and the model) and can take hours on a slow connection;
it resumes where it stopped when started again. An environment made elsewhere can be linked instead.
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

import engine_client
from project import LAYOUT, write_json

FOLDER = LAYOUT.root / "voxcpm"
REPOSITORY = "openbmb/VoxCPM2"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
_LOCK = threading.Lock()
_job = {"running": False, "step": "", "error": "", "log": []}


def venv_python(folder=None):
    return (folder or FOLDER) / "venv" / "Scripts" / "python.exe"


def status():
    runtime = engine_client.voxcpm_runtime()
    with _LOCK:
        job = {**_job, "log": _job["log"][-12:]}
    return {"installed": runtime is not None, "python": str(runtime["python"]) if runtime else "",
            "model": str(runtime["model"]) if runtime else "", "folder": str(FOLDER), "job": job}


def link(python, model):
    """Use an environment and a model folder made elsewhere. Both must exist; the model folder must hold the weights."""
    python, model = Path(str(python).strip().strip('"')), Path(str(model).strip().strip('"'))
    if not python.is_file() or python.suffix.lower() != ".exe":
        raise ValueError("The Python of the VoxCPM2 environment was not found (python.exe).")
    if not (model / "model.safetensors").is_file() or not (model / "config.json").is_file():
        raise ValueError("The model folder must contain model.safetensors and config.json.")
    engine_client.close_engine()
    write_json(engine_client.VOXCPM_CONFIG, {"python": str(python), "model": str(model)})
    return status()


def unlink():
    engine_client.close_engine()
    engine_client.VOXCPM_CONFIG.unlink(missing_ok=True)
    return status()


def _say(step, line=""):
    with _LOCK:
        _job["step"] = step
        if line:
            _job["log"].append(line)


def _run(command, step):
    """Run one install command, keeping its output lines in the log; a failure raises with the last lines."""
    _say(step)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    tail = []
    for line in process.stdout:
        line = line.strip()
        if line:
            tail = (tail + [line])[-6:]
            _say(step, line[:200])
    if process.wait():
        raise RuntimeError(f"{step} failed:\n" + "\n".join(tail))


def install(folder=None):
    """The whole setup, in order; every step is safe to repeat and continues what an earlier run left."""
    folder = Path(folder) if folder else FOLDER
    python = venv_python(folder)
    if not python.is_file():
        _run([sys.executable, "-m", "venv", str(folder / "venv")], "Creating the environment")
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip", "-q"], "Updating pip")
    _run([str(python), "-m", "pip", "install", "torch", "torchaudio", "--index-url", TORCH_INDEX],
         "Installing PyTorch with CUDA (about 3 GB)")
    _run([str(python), "-m", "pip", "install", "voxcpm", "soundfile", "huggingface_hub"], "Installing VoxCPM2")
    model = folder / "model"
    _run([str(python), "-c",
          f"from huggingface_hub import snapshot_download as d; d({REPOSITORY!r}, local_dir={str(model)!r})"],
         "Downloading the VoxCPM2 model (about 5 GB)")
    link(python, model)
    _say("Done")


def start(folder=None):
    """Start the setup in the background. Returns False when one is already running."""
    with _LOCK:
        if _job["running"]:
            return False
        _job.update(running=True, step="Starting", error="", log=[])

    def work():
        try:
            install(folder)
        except Exception as error:
            with _LOCK:
                _job["error"] = str(error)
        finally:
            with _LOCK:
                _job["running"] = False

    threading.Thread(target=work, daemon=True, name="voxcpm-setup").start()
    return True
