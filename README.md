# Agentic File Management System (AFMS)

> A portable, AI-powered, rule-based file organizer that turns any messy folder into a tidy, automatically sorted workspace.

**One command. Sorted Desktop.** Shortcuts and apps stay untouched.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)
![License](https://img.shields.io/badge/License-MIT-green)

---

## What It Does

AFMS scans a target folder (your Desktop, Downloads, etc.), extracts rich metadata from every file (name, extension, size, dates, content summary), and moves each file into a logical subfolder using a **multi-parameter decision engine**.

```
Before                              After
------                              -----
Desktop/                            Desktop/
  architecture.png                    Images/
  Hardware.pdf                          architecture.png
  mod1.png                              mod1.png
  mod2.png                              ...
  setup.msi                          Documents/
  notes.pdf                             Hardware.pdf
  movie.torrent                         notes.pdf
  Chrome.lnk          <-- STAYS -->   Installers/
  MyApp.exe            <-- STAYS -->     setup.msi
                                      Torrents/
                                         movie.torrent
                                      Chrome.lnk       <-- untouched
                                      MyApp.exe         <-- untouched
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-parameter decision engine** | Weighted ranking using file name, extension, size category, dates, and content similarity |
| **Feature extractor** | Extracts `file_name`, `extension`, `size_bytes`, `size_category`, `created_date`, `modified_date`, and more |
| **Config-driven mappings** | Add custom extension-to-category rules in `agent_config.yaml` |
| **Shortcut & app safety** | `.lnk`, `.url`, `.exe`, `.com`, `.msc`, `.pif` files are **never moved** |
| **Dry-run preview** | `--dry-run` shows the full plan without touching anything |
| **Auto-run mode** | `--auto` executes moves silently (great for scripts/scheduled tasks) |
| **Learning mode** | `--learn` reads `corrections.txt` to improve future decisions |
| **Background watcher** | `agent_service.py` monitors folders in real time and sorts new files |
| **System tray app** | `tray_app.py` provides a tray icon for start/stop/status |
| **SQLite audit log** | Every action is recorded in `files.db` for history and rollback |

---

## Quick Start (New Users)

### Prerequisites

- **Python 3.10+** installed ([download](https://www.python.org/downloads/))
- **Git** installed ([download](https://git-scm.com/downloads))
- **Windows 10/11** (Linux/macOS works with minor tweaks)

### Step 1 - Clone the Repository

```powershell
git clone https://github.com/<YOUR-USERNAME>/agentic-file-manager.git
cd agentic-file-manager
```

### Step 2 - Create a Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> **cmd.exe users:** use `.\.venv\Scripts\activate.bat` instead.

### Step 3 - Install Dependencies

```powershell
pip install -r requirements.txt
```

### Step 4 - Preview the Sort (Dry Run)

See what would happen **without moving anything**:

```powershell
python organize_this_folder.py "C:\Users\%USERNAME%\OneDrive\Desktop" --dry-run
```

You'll see a table like:

```
================================================================================
FILE NAME                      | PROPOSED DESTINATION           | DECISION REASON
================================================================================
architecture.png               | Images                         | Extension match
Hardware.pdf                   | Documents                      | Extension match
node-v25.1.0-x64.msi           | Installers                     | Extension match
Dragon Ball.torrent            | Torrents                       | Extension match
================================================================================
```

### Step 5 - Run the Organizer (For Real)

```powershell
python organize_this_folder.py "C:\Users\%USERNAME%\OneDrive\Desktop" --auto
```

`--auto` skips the confirmation prompt and moves files immediately.

### Step 6 - Verify the Result

```powershell
tree "C:\Users\%USERNAME%\OneDrive\Desktop" /F
```

You should see neatly organized subfolders: `Images/`, `Documents/`, `Installers/`, `Torrents/`, etc.

---

## Usage Reference

### CLI Options

```
python organize_this_folder.py [TARGET_FOLDER] [OPTIONS]

Arguments:
  TARGET_FOLDER       Folder to organize (defaults to current directory)

Options:
  --dry-run           Preview moves without executing
  --auto              Execute moves without prompting for confirmation
  --recursive         Process subfolders too
  --learn             Read corrections.txt and update decision rules
```

### Examples

```powershell
# Sort your Desktop (preview first)
python organize_this_folder.py "C:\Users\%USERNAME%\Desktop" --dry-run

# Sort your Downloads folder automatically
python organize_this_folder.py "C:\Users\%USERNAME%\Downloads" --auto

# Sort and learn from past corrections
python organize_this_folder.py "C:\Users\%USERNAME%\Desktop" --learn
```

---

## Background Watcher (Real-Time Sorting)

AFMS can run as a background service that watches folders and sorts new files as they arrive:

### Start the Services

```powershell
# Start the file watcher
python agent_service.py

# (Optional) Start the system tray icon
python tray_app.py
```

### Stop the Services

**Option A - Double-click** the `stop_afms.bat` file in the project folder.

**Option B - PowerShell command:**

```powershell
powershell -ExecutionPolicy Bypass -File stop_afms.ps1
```

**Option C - Manual kill (stops ALL Python processes):**

```powershell
Stop-Process -Name python -Force
```

**Option D - Kill specific process by PID:**

```powershell
# Find the PID
Get-Process -Name python | Format-Table Id, ProcessName -AutoSize

# Kill it
Stop-Process -Id <PID> -Force
```

---

## Customisation

### Adding New File Types

Edit `agent_config.yaml`:

```yaml
file_type_mappings:
  ".msi":     "Installers"
  ".torrent": "Torrents"
  ".pdf":     "Documents"
  ".mkv":     "Videos"
  ".mp3":     "Music"
  # Add your own mappings here...
```

### Adjusting Decision Weights

Modify the `weights` section in `agent_config.yaml` to control how much influence each attribute has:

```yaml
weights:
  extension: 0.30
  name_similarity: 0.25
  size_category: 0.15
  content: 0.20
  date: 0.10
```

### Teaching the Engine (Learning Mode)

1. Create a `corrections.txt` file in the target folder:

```
C:\Desktop\report.pdf -> C:\Desktop\Work\report.pdf
C:\Desktop\vacation.jpg -> C:\Desktop\Personal\vacation.jpg
```

2. Run the learning command:

```powershell
python organize_this_folder.py "C:\Users\%USERNAME%\Desktop" --learn
```

The engine updates its `PreferenceMiner` rules and applies them in future runs.

---

## Project Structure

```
agentic_file_manager/
|-- .gitignore                  # Git ignore rules
|-- README.md                   # This file
|-- requirements.txt            # Python dependencies
|-- agent_config.yaml           # Extension mappings & weights
|
|-- organize_this_folder.py     # CLI entry point (one-shot organizer)
|-- agent_service.py            # Background file watcher
|-- tray_app.py                 # System tray icon
|-- stop_afms.ps1               # Stop script (PowerShell)
|-- stop_afms.bat               # Stop script (double-click)
|
|-- core/
|   |-- scanner.py              # Folder scanning logic
|   +-- models.py               # Data models
|
|-- services/
|   |-- feature_extractor.py    # File attribute extraction
|   |-- multi_parameter_decision_engine.py  # Weighted ranking engine
|   |-- file_executor.py        # File move operations
|   |-- action_logger.py        # SQLite audit logger
|   |-- ai_categorizer.py       # AI/LLM categorisation (optional)
|   |-- embeddings.py           # Sentence embeddings
|   |-- similarity_service.py   # Content similarity search
|   |-- vector_store.py         # FAISS vector index
|   |-- correction_tracker.py   # User correction storage
|   +-- preference_miner.py     # Rule learning from corrections
|
|-- database/
|   |-- db_manager.py           # SQLite connection manager
|   +-- schema.sql              # Database schema
|
|-- config/
|   +-- settings.py             # Runtime settings
|
+-- tests/
    +-- test_folder/            # Sample files for testing
```

---

## Environment Variables (Optional)

| Variable | Description | Default |
|----------|-------------|---------|
| `AFMS_DATABASE_PATH` | Path to SQLite database | `./files.db` |
| `AFMS_LOG_PATH` | Log file directory | `./logs/` |
| `AFMS_LOG_LEVEL` | Logging level | `INFO` |
| `OPENAI_API_KEY` | OpenAI API key (for AI categorisation) | None |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python` not found | Install Python 3.10+ and add to PATH |
| `No loose matching files found` | The folder is already organised (no loose files at root level) |
| `AI categorization failed` | Normal offline - the system falls back to local extension rules |
| `WinError 10061` in logs | LLM server not running - ignored, local rules take over |
| Script runs slowly on images | BLIP model downloads on first run (~1GB). Cached afterward |

---

## Contributing

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-rule`)
3. Make changes and test (`python -m pytest tests/`)
4. Open a Pull Request

---

## License

MIT License - free to use, modify, and distribute. See `LICENSE` for details.

---

*Built with Python, FAISS, Sentence Transformers, and a passion for tidy desktops.*
