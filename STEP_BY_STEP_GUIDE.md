# Step-by-Step Guide: Running the Agentic File Manager

This guide provides step-by-step instructions on how to use and demonstrate the core features of the Agentic File Manager.

## 1. Setup and Initialization

First, ensure you have the virtual environment activated and dependencies installed.

```powershell
# Create and activate the virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install required packages
pip install -r requirements.txt
```

---

## 2. Testing the CLI Organizer (One-Shot Organization)

If you have a messy folder (e.g., `test_demo`) that you want to organize instantly:

1. **View the initial state of the folder:**
   ```powershell
   tree test_demo /F
   ```
   *Notice the loose files and unstructured layout.*

2. **Run the organizer:**
   ```powershell
   python organize_this_folder.py test_demo --auto
   ```
   *The `--auto` flag ensures it processes all files without asking for a `y/n` prompt. It uses the Multi-Parameter Decision Engine to extract features and classify files into specific subfolders like `Documents/PDFs` or `Software/Archives`.*

3. **Verify the results:**
   ```powershell
   tree test_demo /F
   ```
   *You will notice the files are now neatly structured. Similar files are grouped dynamically, and if a suitable subfolder already existed, the files were smartly routed there.*

---

## 3. Testing the Background Monitor (Real-Time Organization)

To have the agent watch a folder and organize files live as they arrive:

1. **Configure the Watch Folder:**
   Open `agent_config.yaml` and ensure your target folder is listed under `watch_folders`:
   ```yaml
   watch_folders:
     - C:\path\to\your\test_demo
   ```

2. **Start the Background Service:**
   In your terminal, run the following command and leave it open:
   ```powershell
   python agent_service.py
   ```
   *The system is now actively monitoring the folder.*

3. **Trigger the Magic:**
   - Open your File Explorer and navigate to your watched folder.
   - Drag and drop a new file (e.g., a `.pdf`, `.zip`, or `.jpg`) into the folder.
   - Watch as the background agent instantly detects the new file and organizes it into the correct categorized subfolder automatically!

---

## 4. Running the Web Dashboard (Optional)

If you want a graphical interface to monitor the agent's activity and see file health:

```powershell
streamlit run app.py
```
*When prompted for a password in the browser, enter `admin` to unlock the dashboard.*
