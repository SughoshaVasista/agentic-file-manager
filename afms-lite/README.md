# AFMS Lite

Lightweight AI-powered file organizer. 3 files. 2 dependencies. <1s startup.

## Setup
```bash
pip install -r afms-lite/requirements.txt
```

## One-shot organize
```bash
python afms-lite/watcher.py --once "C:/Users/YourName/Desktop" --auto
python afms-lite/watcher.py --once "C:/Users/YourName/Desktop" --dry-run
```

## Background watcher (sorts new files as they arrive)
```bash
python afms-lite/watcher.py
```

## Teach it a correction
Edit `afms-lite/rules.json` directly and add a fnmatch pattern:
```json
{ "my_pattern_*": "FolderName" }
```
No restart needed — rules are re-read on every organize run.

## LLM setup (optional — works offline without it)
In `config.yaml` set:
```yaml
llm:
  provider: "openai"
  openai_api_key: "sk-..."
```
Or set env var `OPENAI_API_KEY`.
Without an LLM key, organizer falls back to extension + rules — still fast.

## Protected folders
In `config.yaml` add full paths under `protected_folders:`.
These folders are never organized, ever.

## View move history
```bash
cat afms-lite/moves.log
```
