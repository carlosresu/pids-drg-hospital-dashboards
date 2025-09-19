# 📄 Automated Hospital PDF Exporter (Power BI + Playwright)

This project automates the export of **hospital-specific PDF reports** from a Power BI dashboard.
It uses [Playwright](https://playwright.dev/python/) for headless browser automation, supports **parallel workers** via `ProcessPoolExecutor`, and includes robust **retry logic** for failed hospitals.

---

## 🚀 Features

- **Headless PDF export** of Power BI dashboards
- **Parallel processing** with configurable number of workers
- **Retry mechanism** for failed hospitals (`failed_hospitals.csv`)
- **Automatic Playwright/Chromium installation**
- **Debug & screenshot modes** for troubleshooting
- **Normalized text matching** to avoid whitespace/unicode mismatches
- **Safe filenames** for each hospital report
- **Timestamped output directories** for clean runs

---

## 📂 Project Structure

```
project-root/
│
├── data/
│   ├── inputs/
│   │   ├── hospitals_new.csv        # Main hospital list (input)
│   │   └── failed_hospitals.csv     # Retry list (auto-generated)
│   └── outputs/
│       └── SB_Report_<TIMESTAMP>/   # PDF reports generated per run
│
├── exporter.py                      # Main script (this file)
└── README.md                        # Documentation
```

---

## 🛠️ Requirements

- Python **3.8+**
- [Playwright for Python](https://playwright.dev/python/)
- Chromium (installed automatically by script)

---

## 📦 Setup

1. **Clone repo / copy script** into your project directory.

2. **Install Python dependencies** (the script auto-installs Playwright if missing):

   ```bash
   pip install playwright
   playwright install chromium
   ```

   > ✅ If you run the script directly, it will install missing dependencies automatically.

3. **Prepare your hospital list**
   Place a CSV at:

   ```
   data/inputs/hospitals_new.csv
   ```

   with at least one column:

   ```csv
   faci_name
   Hospital A
   Hospital B
   Hospital C
   ```

---

## ▶️ Usage

Run the exporter:

```bash
python exporter.py
```

### Workflow

1. Script reads hospitals from `hospitals_new.csv`
2. Each hospital name is:

   - searched in the Power BI dropdown
   - selected and verified
   - exported as `SB_Report_<DATE>_<Hospital>.pdf`

3. Reports are saved in:

   ```
   data/outputs/SB_Report_<TIMESTAMP>/
   ```

4. Failures are written to `data/inputs/failed_hospitals.csv`

   - The script will automatically retry failed hospitals on the next attempt.

---

## ⚙️ Configuration

Modify these **global variables** inside `exporter.py`:

| Variable              | Description                      | Default                 |
| --------------------- | -------------------------------- | ----------------------- |
| `POWER_BI_URL`        | Power BI dashboard URL           | _(demo link included)_  |
| `WAIT_TIMES`          | Dict of UI wait times in seconds | `{iframe_wait: 3, ...}` |
| `DROPDOWN_SELECTOR`   | CSS selector for dropdown        | `.slicer-restatement`   |
| `SEARCH_BAR_SELECTOR` | CSS selector for search input    | `input.searchInput`     |
| `NUM_WORKERS`         | Number of parallel workers       | `4`                     |
| `TO_DEBUG`            | Print debug logs                 | `False`                 |
| `ENABLE_SCREENSHOT`   | Save screenshots on failure      | `False`                 |

---

## 🧩 How It Works

1. **Dependency Check**

   - Installs Playwright + Chromium if missing (one-time).

2. **Hospital Processing**

   - Hospitals are divided into equal subsets across workers.
   - Each worker launches its own Chromium instance.

3. **Dropdown Interaction**

   - Script opens dropdown → searches hospital → selects match.
   - Uses **normalized text** (whitespace + unicode safe).

4. **PDF Export**

   - After selection, the current dashboard is exported as PDF.
   - Filenames are sanitized to avoid invalid characters.

5. **Failure Handling**

   - If selection or export fails → hospital goes to `failed_hospitals.csv`.
   - Retries continue until no hospitals remain failed.

---

## 🐞 Debugging

- Enable debug logs:

  ```python
  TO_DEBUG = True
  ```

- Enable screenshots for failed hospitals:

  ```python
  ENABLE_SCREENSHOT = True
  ```

  Screenshots are saved alongside PDFs.

---

## 📊 Example Output

```
data/outputs/SB_Report_20250919_143015/
│
├── SB_Report_20250919_Hospital_A.pdf
├── SB_Report_20250919_Hospital_B.pdf
└── SB_Report_20250919_Hospital_C.pdf
```

---

## 💡 Tips

- If some hospitals repeatedly fail, check:

  - The exact spelling of names in `hospitals_new.csv`
  - That they appear in the Power BI dropdown

- You can manually edit `failed_hospitals.csv` and rerun.
