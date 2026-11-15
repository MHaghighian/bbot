# BBOT for Windows

This repository ships a **Windows-native** build of BBOT.

- **No Docker**
- **No WSL**
- **No admin / UAC**

## Download

Get **`bbot.exe`** from:

**https://github.com/MHaghighian/bbot/releases**

## Run

```powershell
.\bbot.exe --help
.\bbot.exe -t example.com -m crt --yes
.\bbot.exe -t example.com -p subdomain-enum -rf passive --yes
```

## Rebuild the .exe (developers)

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build_exe.ps1
```

Output: `dist\windows\bbot.exe`

## Dev run (without packaging)

```powershell
uv sync --python 3.12 --no-dev
.\.venv\Scripts\bbot.exe --help
```

## Windows notes

- Target platform: **Windows x64**
- HTTP uses **httpx** (blasthttp has no Windows wheels)
- Ansible auto-install of Linux tools is disabled
- Prefer **passive** presets; Linux-only binaries (masscan, nuclei, gowitness, …) are not auto-installed
- Cloud signature download may warn behind some proxies; scans still run
