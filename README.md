# Xiaozhi Diagnostic Center

A cross-platform GUI tool for diagnosing Xiaozhi ESP32 device connection issues.

## Features

### 1. Connection Diagnosis
- Checks Docker, containers, ports (8000/8002/8003)
- Tests OTA endpoint and displays the correct device OTA address
- Validates IP consistency between database and server
- Monitors device connections in real-time (45 second capture)
- Alerts about incorrect OTA addresses (including the common trailing-slash mistake)

### 2. Conversation Health
- Analyzes server logs for LLM/TTS/ASR errors
- Detects the "idle auto-goodbye" feature (crying face then disconnect)
- Identifies unconfigured API keys
- Reports weather plugin auth failures

### 3. LAN Device Scanner
- Scans the local network for all devices
- Cross-references with registered Xiaozhi devices in the database
- Shows online/offline status, alias, board type, last connection time

## Download

Go to [Releases](../../releases) and download:
- **Windows**: `XiaozhiDiagnostic.exe`
- **macOS**: `XiaozhiDiagnostic.dmg`

## Usage

1. Place the executable in the same directory as your Xiaozhi server files (where `.last_ip` and `changeIp.bat` live)
2. Make sure Docker is running with the Xiaozhi containers
3. Run the diagnostic tool
4. Follow the tabs: Connection -> Conversation Health -> Devices

## Building from Source

```bash
pip install pyinstaller==6.11.1
pyinstaller build.spec --noconfirm
```

## Requirements

- Python 3.9+ (for building from source)
- Docker (must be running with Xiaozhi containers for full functionality)
- The tool uses only built-in Python libraries (tkinter, subprocess, socket, etc.)
