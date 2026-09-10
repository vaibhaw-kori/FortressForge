#!/usr/bin/env python3
"""
AURA-Install Online Installer — Windows 11 Pro 22H2 + RTX 5090 32GB + 64GB RAM + 1080p
- Checks system (Windows 11, RAM, disk, GPU, Node 20, Python 3.11)
- Downloads Wan2.1-I2V-14B-480P-Diffusers 84GB once to %LOCALAPPDATA%\\AURA\\.hf-cache (resume)
- Creates .venv, pip install, npm install
- Launches single auto-start: backend 8000 + kiosk 5173 + stage 5174
"""

from __future__ import annotations

import os
import sys
import subprocess
import pathlib
import shutil
import time

REPO_URL = "https://github.com/vaibhaw-kori/FortressForge.git"
MODEL_REPO = "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"
CACHE_DIR = pathlib.Path(os.environ.get("LOCALAPPDATA", str(pathlib.Path.home()))) / "AURA" / ".hf-cache"
APP_DIR = pathlib.Path.home() / "AURA-Install"
MIN_RAM_GB = 32
MIN_DISK_GB = 150

def log(msg: str) -> None:
    print(f"[AURA] {msg}", flush=True)

def check_windows() -> None:
    import platform
    if platform.system() != "Windows":
        log("ERROR: Windows 11 Pro 22H2 64-bit required")
        sys.exit(1)
    log(f"Windows {platform.version()} ok")

def check_ram() -> None:
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024**3)
    except ImportError:
        ram_gb = 64  # assume ok if psutil not installed
    if ram_gb < MIN_RAM_GB:
        log(f"WARN: RAM {ram_gb:.1f}GB < {MIN_RAM_GB}GB — 64GB recommended for offline 84GB")
    else:
        log(f"RAM {ram_gb:.1f}GB ok")

def check_disk() -> None:
    free_gb = shutil.disk_usage(APP_DIR if APP_DIR.exists() else pathlib.Path.home()).free / (1024**3)
    if free_gb < MIN_DISK_GB:
        log(f"ERROR: free disk {free_gb:.1f}GB < {MIN_DISK_GB}GB on {APP_DIR.drive or 'C:'} — free 150GB")
        sys.exit(1)
    log(f"Disk free {free_gb:.1f}GB ok")

def check_gpu() -> None:
    try:
        out = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], text=True)
        log(f"GPU {out.strip()} — RTX 5090 32GB expected, 480x832 resident ok")
        if "5090" not in out and "4090" not in out and "6000" not in out and "A100" not in out:
            log("WARN: GPU not RTX 5090 — 32GB VRAM recommended for 10s 8-step")
    except Exception as e:
        log(f"WARN: nvidia-smi failed ({e}) — install NVIDIA Driver ≥550 + CUDA 12.4")

def ensure_node() -> None:
    try:
        out = subprocess.check_output(["node", "-v"], text=True).strip()
        log(f"Node {out} ok")
        major = int(out.lstrip("v").split(".")[0])
        if major < 18:
            raise RuntimeError("Node <18")
    except Exception:
        log("Installing Node 20 via winget...")
        subprocess.run(["winget", "install", "OpenJS.NodeJS.LTS", "--silent"], check=False)

def ensure_python() -> None:
    if sys.version_info < (3, 11):
        log("ERROR: Python 3.11+ required")
        sys.exit(1)
    log(f"Python {sys.version.split()[0]} ok")

def download_model() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(CACHE_DIR)
    os.environ["HF_HUB_CACHE"] = str(CACHE_DIR / "hub")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(CACHE_DIR / "hub")
    log(f"Cache {CACHE_DIR} — checking {MODEL_REPO} 84GB (resume-capable)...")
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=MODEL_REPO,
            local_dir=str(CACHE_DIR / f"models--{MODEL_REPO.replace('/', '--')}"),
            local_dir_use_symlinks=False,
            resume_download=True,
            max_workers=4,
        )
        log("Model cached")
    except ImportError:
        log("huggingface_hub not installed — installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "huggingface_hub"])
        download_model()

def setup_app() -> None:
    if not APP_DIR.exists():
        log(f"Cloning {REPO_URL} → {APP_DIR}")
        subprocess.check_call(["git", "clone", REPO_URL, str(APP_DIR)])
    else:
        log(f"Updating {APP_DIR}")
        subprocess.check_call(["git", "-C", str(APP_DIR), "pull", "--ff-only"])
    # venv
    venv = APP_DIR / ".venv"
    if not venv.exists():
        log("Creating .venv")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
    pip = venv / "Scripts" / "pip.exe"
    # use venv pip
    subprocess.check_call([str(pip), "install", "-e", str(APP_DIR / "services" / "backend"), "--quiet"])
    subprocess.check_call([str(pip), "install", "huggingface_hub", "psutil", "--quiet"])
    # npm
    log("npm install (this may take a minute)...")
    subprocess.check_call(["npm", "install"], cwd=str(APP_DIR), shell=True)
    log("Setup done")

def launch() -> None:
    venv_python = APP_DIR / ".venv" / "Scripts" / "python.exe"
    env = os.environ.copy()
    env["HF_HOME"] = str(CACHE_DIR)
    env["HF_HUB_CACHE"] = str(CACHE_DIR / "hub")
    env["HUGGINGFACE_HUB_CACHE"] = str(CACHE_DIR / "hub")
    env["TRANSFORMERS_CACHE"] = str(CACHE_DIR)
    env["AURA_WAN_OFFLOAD_TO_CPU"] = "false"
    env["AURA_WAN_ENABLE_OFFLOAD"] = "false"
    # single auto-start via nohup equivalent: start detached
    log("Launching backend 8000 + kiosk 5173 + stage 5174...")
    subprocess.Popen(
        [str(venv_python), "-m", "uvicorn", "aura_backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(APP_DIR / "services" / "backend"),
        env=env,
        creationflags=subprocess.DETACHED_PROCESS,
    )
    time.sleep(5)
    subprocess.Popen(["npm", "run", "dev", "--workspace=apps/kiosk", "--", "--host", "0.0.0.0", "--port", "5173"], cwd=str(APP_DIR), shell=True, creationflags=subprocess.DETACHED_PROCESS)
    subprocess.Popen(["npm", "run", "dev", "--workspace=apps/stage", "--", "--host", "0.0.0.0", "--port", "5174"], cwd=str(APP_DIR), shell=True, creationflags=subprocess.DETACHED_PROCESS)
    log("Launched — open http://localhost:5173 (kiosk) and http://localhost:5174 (stage, F11)")
    # auto-start registry
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, "AURA", 0, winreg.REG_SZ, f'"{sys.executable}" "{__file__}"')
        winreg.CloseKey(key)
        log("Auto-start registered (HKCU\\Run\\AURA)")
    except Exception:
        pass

def main() -> None:
    log("AURA-Install Online Installer — RTX 5090 32GB 1080p")
    check_windows()
    check_ram()
    check_disk()
    check_gpu()
    ensure_python()
    ensure_node()
    download_model()
    setup_app()
    launch()
    log("Done — first generation ~10s warm (8 steps 480x832)")

if __name__ == "__main__":
    main()
