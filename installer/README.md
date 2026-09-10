# AURA-Install — Online Installer (Windows 11 Pro 22H2, RTX 5090 32GB, 1080p)

Online-installer `~5MB` — first run downloads `Wan2.1-I2V-14B-480P-Diffusers` `84GB` once to `%LOCALAPPDATA%\AURA\.hf-cache` (resume-capable), then auto-starts:

- Backend `FastAPI` `0.0.0.0:8000`
- Kiosk `Vite` `0.0.0.0:5173` → `http://localhost:5173`
- Stage `Vite` `0.0.0.0:5174` → `http://localhost:5174`

Optimized for `RTX 5090 32GB Blackwell` `64GB RAM` `1080p` camera `→ 480x832` native `16:9→9:16` center-crop (no stretch), `8 steps 6.8/120/0.52` `~10s` warm.

## Build (dev machine, not client)

```powershell
# 1. Python 3.11 + Node 20 required
py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install pyinstaller==6.10 httpx huggingface_hub
# 2. Build exe
powershell -ExecutionPolicy Bypass -File installer\build.ps1
# → dist\AURA-Installer.exe  ~5MB
```

## Client first run (offline after download)

```powershell
.\AURA-Installer.exe
# 1. Checks: Windows 11, 64GB RAM, RTX 5090, free disk ≥150GB, Node 20, Python 3.11
# 2. Downloads model 84GB to %LOCALAPPDATA%\AURA\.hf-cache (shows progress, resume on fail)
# 3. Creates .venv, pip install -e ./services/backend, npm install
# 4. Launches single auto-start (no console): backend + kiosk + stage, opens kiosk in Chrome
```

Second run skips download (cache hit) → `~5s` launch.

## Why not `git push` 84GB

GitHub limit `100MB`; `84GB` would break `git clone`. This repo holds **installer code only**; model is fetched at install via `huggingface_hub` with `HF_HOME`.

## Single auto-start

Installer writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\AURA` to launch on boot. Disable via `Task Manager → Startup`.

## Troubleshooting

- `Not enough free disk` → free `150GB` on `C:`.
- `CUDA not available` → install `NVIDIA Driver ≥550` + `CUDA 12.4`.
- `Camera warming up` → Chrome → address bar camera → Allow → `Ctrl+Shift+R`.
