import os
import csv

# --- Config ---
OUTPUT_DIR = r"C:\Users\resur\pids-drg-hospital-dashboards\data\outputs\SB_Report_20250723_160119"
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "exported_hospitals.csv")

# --- Extract hospital names from filenames ---
hospital_names = []

for fname in os.listdir(OUTPUT_DIR):
    if fname.endswith(".pdf") and fname.startswith("SB_Report_"):
        name = fname[len("SB_Report_"):-len("_20250723_160119.pdf")]
        hospital_names.append(name)

# --- Save to CSV ---
with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["hospital_name"])
    for name in hospital_names:
        writer.writerow([name])

print(f"✅ Saved {len(hospital_names)} hospital names to {OUTPUT_CSV}")
