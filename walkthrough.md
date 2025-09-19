# End-to-End Walkthrough

This is a walkthrough guide. It shows how to:

1. Install **GitHub Desktop**
2. **Clone** the repository: `https://github.com/pids-drg-team/pids-drg-hospital-dashboards`
3. Install **Python**
4. Confirm the repo’s folder structure (already includes the exporter script)
5. Add the hospital CSV
6. Run the exporter to generate PDFs

**What the exporter does:** Opens a Power BI dashboard, selects each hospital from the slicer, and exports **one PDF per hospital**. If some fail, it retries them from a generated list.

---

## 1) Install GitHub Desktop

1. Open your browser (Chrome or Edge).
2. Visit [**https://desktop.github.com/**](https://desktop.github.com/)
3. Click **Download for Windows** and run the installer. No special options needed.
4. Open **GitHub Desktop** after install and **sign in** (create a free GitHub account if you don’t have one).

---

## 2) Clone the Repository (Get the Code)

1. In **GitHub Desktop**: go to **File → Clone repository…**
2. Click the **URL** tab.
3. Paste this link:  
   https://github.com/pids-drg-team/pids-drg-hospital-dashboards
4. For **Local Path**, choose a convenient folder, e.g.:  
   C:/HospitalDashboards
5. Click **Clone**. Wait for the download to finish.

**Check your files:**

- Open **File Explorer** → go to `C:/HospitalDashboards/pids-drg-hospital-dashboards`.
- You should see this structure (key parts):
  ```
  project-root/
  │
  ├── data/
  │   ├── inputs/
  │   │   ├── hospitals.csv            # Main hospital list (get the latest file from the PIDS Health Team)
  │   │   └── failed_hospitals.csv     # Retry list (auto-generated)
  │   └── outputs/
  │       └── SB_Report_<TIMESTAMP>/   # PDF reports generated per run
  │
  ├── scripts/
  │   └── exporter.py                  # Main script (already in the repo)
  └── README.md                        # Documentation
  ```

**Updating later:** Open GitHub Desktop → select the repo → **Fetch origin** → **Pull** to get the latest changes.

---

## 3) Install Python (One Time)

1. Go to [**https://www.python.org/downloads/windows/**](https://www.python.org/downloads/windows/)
2. Download the latest **Windows installer (64-bit)**.
3. Run the installer and **check the box** that says **“Add python.exe to PATH.”**
4. Click **Install Now** and wait for it to finish.

**Verify:**

- Press **Windows Key + R**, type `cmd`, press **Enter**.
- In the black window, type:
  ```
  python --version
  ```
  You should see something like `Python 3.11.x`.

---

## 4) Add or Prepare Your Hospital List (CSV)

1. Contact the **PIDS Health Team** to get the latest `hospitals.csv`.
2. Save the file as **`hospitals.csv`**.
3. Place the file here (replace existing if present):  
   C:/HospitalDashboards/pids-drg-hospital-dashboards/data/inputs/hospitals.csv

Tip: Start with 2–3 hospitals for a quick verification before running the full list.

---

## 5) Install the Automation Tool (Playwright)

1. Open **Command Prompt** (Windows Key → type `cmd` → Enter).
2. Go to the repo folder by typing and pressing Enter:
   ```
   cd C:/HospitalDashboards/pids-drg-hospital-dashboards
   ```
3. Install the tool that controls the browser (run each line and wait):
   ```
   pip install playwright
   python -m playwright install chromium
   ```

This downloads **Chromium** (the browser) for automation. You do this once per computer.

---

## 6) (Optional) Set the Power BI Link in the Script

- Open this file in **Notepad**:  
  C:/HospitalDashboards/pids-drg-hospital-dashboards/scripts/exporter.py
- At the top, find `POWER_BI_URL`. If you’re using your own dashboard, paste your **public or embed** link there.
- Save and close Notepad.

**Important:** Headless automation can’t click through sign-in screens. Use a **public view** link for the dashboard.

---

## 7) Run the Exporter (From the Repo’s Scripts Folder)

1. Make sure your Command Prompt is in the repo root:
   ```
   C:/HospitalDashboards/pids-drg-hospital-dashboards>
   ```
2. Start the exporter by pointing to the `scripts` folder:
   ```
   python scripts/exporter.py
   ```

**What you’ll see:**

- A message like `=== Attempt 1 ===`.
- Progress for each hospital.
- A new folder inside `data/outputs` named like `SB_Report_YYYYMMDD_HHMMSS`.

**Example output:**

```
C:/HospitalDashboards/pids-drg-hospital-dashboards/data/outputs/SB_Report_20250919_143015
 ├─ SB_Report_20250919_Hospital A.pdf
 ├─ SB_Report_20250919_Hospital B.pdf
 └─ SB_Report_20250919_Hospital C.pdf
```

If some hospitals fail, the script creates:

```
C:/HospitalDashboards/pids-drg-hospital-dashboards/data/inputs/failed_hospitals.csv
```

It will **retry** those automatically on the next loop.

---

## 8) Beginner-Friendly Troubleshooting

- **Python not found**
  - Reinstall Python and make sure you checked **Add python.exe to PATH**.
  - Close and reopen Command Prompt.
- **Playwright/Chromium didn’t install**
  - Run these again in Command Prompt (one by one):
    ```
    pip install playwright
    python -m playwright install chromium
    ```
- **Power BI asks to sign in**
  - Use a **public view** or **embed** link in `POWER_BI_URL`.
- **Hospitals not found in the dropdown**
  - Make sure the names in `hospitals.csv` match the slicer labels in the dashboard (spelling matters).
- **PDFs are blank or not saved**
  - Your internet may be slow. Open this file:  
    C:/HospitalDashboards/pids-drg-hospital-dashboards/scripts/exporter.py  
    Increase these timings near the top:
    ```python
    WAIT_TIMES = {
        "iframe_wait": 3,
        "dropdown_sleep": 3,
        "search_sleep": 3,
        "visual_update_sleep": 3
    }
    ```
    Try changing the 3’s to 5 or 7 and save the file.
- **Watch the browser while recording the video**
  - In `scripts/exporter.py`, find:
    ```python
    browser = p.chromium.launch(headless=True)
    ```
  - Change to:
    ```python
    browser = p.chromium.launch(headless=False, slow_mo=250)
    ```
  - This opens a visible window and slows actions.

---

## 9) Recap — What the Viewer Will Do (Simple Checklist)

1. Install **GitHub Desktop** and **clone** the repository.
2. Install **Python**.
3. Ensure the repo already contains `scripts/exporter.py` (no need to create it).
4. Contact the **PIDS Health Team** to get the latest `hospitals.csv`, save it in `data/inputs`.
5. Open **Command Prompt**, go to the repo folder, and run:
   ```
   python scripts/exporter.py
   ```
6. Collect PDFs from `data/outputs/SB_Report_<timestamp>`.

---

## 10) Keeping Everything Current (Optional)

- Open **GitHub Desktop**, select the repo, click **Fetch origin** then **Pull** to get the latest files.
- If the Power BI report design changes, the script’s **CSS selectors** near the top may need an update (ask a tech helper to adjust those lines).
