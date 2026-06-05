"""Helper script to verify and set up the offline local LLM capability using Ollama."""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from pathlib import Path
import sys

import yaml

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1"


def check_ollama_status() -> bool:
    """Check if the local Ollama service is running."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/", timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def ensure_ollama_running() -> bool:
    """Check if Ollama is running, and if not, attempt to launch the background service."""
    if check_ollama_status():
        return True
        
    print("[INFO] Ollama is not running. Attempting to start it in the background...")
    import subprocess
    import time
    try:
        # Launch the local 'ollama serve' daemon
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x00000008  # DETACHED_PROCESS on Windows
        )
        # Give it up to 6 seconds to bind to port 11434
        for i in range(6):
            time.sleep(1)
            if check_ollama_status():
                print("[SUCCESS] Ollama service started successfully!")
                return True
    except Exception as e:
        print(f"[WARNING] Auto-start failed: {e}")
        
    return False


def get_installed_models() -> list[str]:
    """Retrieve list of locally installed Ollama models."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
            return [m["name"].split(":")[0] for m in data.get("models", [])]
    except Exception:
        return []


def pull_model(model_name: str) -> bool:
    """Pull the specified model from Ollama library."""
    print(f"Requesting Ollama to pull model '{model_name}' locally...")
    print("Please wait, this may take a few minutes depending on your internet connection...")
    
    url = f"{OLLAMA_URL}/api/pull"
    data = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
    
    try:
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
            if result.get("status") == "success":
                print(f"\n[SUCCESS] Model '{model_name}' is ready to use offline!")
                return True
            else:
                print(f"\n[INFO] Ollama returned status: {result}")
                return True
    except Exception as e:
        print(f"\n[ERROR] Failed to pull model '{model_name}': {e}")
        return False


def main() -> None:
    print("=======================================================================")
    print("            Offline Local AI Organization Setup (Ollama)")
    print("=======================================================================")
    
    # 1. Ensure Ollama is running
    if not ensure_ollama_running():
        print("[ERROR] Local Ollama service is not running on http://localhost:11434")
        print("\nTo set up local smart AI organization:")
        print("1. Download and install Ollama from: https://ollama.com")
        print("2. Launch the Ollama application on your computer.")
        print("3. Re-run this setup script.")
        print("\nUsing keyword-based offline classification ('local') in the meantime.")
        sys.exit(1)
        
    print("[INFO] Ollama service detected running locally!")
    
    # 2. Check installed models
    models = get_installed_models()
    print(f"[INFO] Installed models found: {models}")
    
    target_model = DEFAULT_MODEL
    if target_model not in models:
        print(f"[WARNING] Model '{target_model}' is not installed locally.")
        success = pull_model(target_model)
        if not success:
            # Fallback to check if they have any model at all we can use
            if models:
                target_model = models[0]
                print(f"[INFO] Falling back to use already installed model: '{target_model}'")
            else:
                print("[ERROR] No models available. Please run 'ollama run llama3.1' in your terminal.")
                sys.exit(1)
    else:
        print(f"[INFO] Model '{target_model}' is already downloaded and ready.")
        
    # 3. Update agent_config.yaml
    config_path = Path(__file__).parent.resolve() / "agent_config.yaml"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            
            config["llm_model"] = "ollama"
            
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, default_flow_style=False)
                
            print(f"[SUCCESS] Updated 'agent_config.yaml' to use local offline model: '{target_model}'")
        except Exception as e:
            print(f"[ERROR] Failed to update agent_config.yaml: {e}")
    else:
        print("[WARNING] agent_config.yaml not found, could not update settings.")


if __name__ == "__main__":
    main()
