import os
import csv
import re

# --- Config ---
HOSPITALS_CSV = r"C:\Users\resur\pids-drg-hospital-dashboards\data\inputs\hospitals.csv"
OUTPUT_DIR = r"C:\Users\resur\pids-drg-hospital-dashboards\data\outputs\SB_Report_20250723_153139"
MISSING_CSV = os.path.join(OUTPUT_DIR, "missing_pdfs.csv")

# --- Normalization Function (same as in PDF script) ---
def normalize(name):
    name = re.sub(r"[\\/*?:\"<>|]", "_", name)   # Replace invalid filename characters
    name = " ".join(name.strip().split())        # Collapse whitespace
    return name

# --- Load hospital list ---
with open(HOSPITALS_CSV, newline="", encoding="utf-8") as f:
    hospitals = [row[0] for row in csv.reader(f) if row]
if hospitals and hospitals[0].strip().lower() == "facility_name":
    hospitals = hospitals[1:]

# --- Extract correct timestamp from folder name ---
runstamp = os.path.basename(OUTPUT_DIR).replace("SB_Report_", "")

# --- Construct expected PDF filenames ---
expected_pdf_names = {
    f"SB_Report_{normalize(h)}_{runstamp}.pdf": h
    for h in hospitals
}

# --- Compare with actual files ---
actual_pdf_files = set(f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".pdf"))
missing_pdfs = [h for fname, h in expected_pdf_names.items() if fname not in actual_pdf_files]

# --- Output result ---
print(f"Total hospitals in CSV: {len(hospitals)}")
print(f"PDFs found: {len(actual_pdf_files)}")
print(f"Missing: {len(missing_pdfs)}\n")

if missing_pdfs:
    print("Saving missing list to:", MISSING_CSV)
    with open(MISSING_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([[h] for h in missing_pdfs])
else:
    print("✅ All hospitals successfully matched to PDFs.")
