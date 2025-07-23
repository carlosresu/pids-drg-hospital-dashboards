import os
import re
import sys
import csv
import time
import math
import subprocess
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from playwright.sync_api import sync_playwright

# ---------------- Configuration ----------------
POWER_BI_URL = "https://app.powerbi.com/view?r=eyJrIjoiNDlmNjliNTUtOTEwOS00NTFhLWIwMGQtNzk1Y2VlYWIwNjBjIiwidCI6ImM4MzU0YWFmLWVjYzUtNGZmNy05NTkwLWRmYzRmN2MxZjM2MSIsImMiOjEwfQ%3D%3D"
WAIT_TIMES = {
    "iframe_wait": 1,
    "dropdown_sleep": 1,
    "search_sleep": 1,
    "visual_update_sleep": 1,
}
DROPDOWN_SELECTOR = ".slicer-restatement"
SEARCH_BAR_SELECTOR = "input.searchInput"
SLICER_ITEM_SELECTOR = "div.slicerItemContainer"
IFRAME_SELECTOR = "iframe[src*='powerbi']"
HOSPITALS_CSV = os.path.join("data", "inputs", "hospitals.csv")
TO_DEBUG = False
ENABLE_SCREENSHOT = False
NUM_WORKERS = 16
# ------------------------------------------------

def debug_sleep(name):
    time.sleep(WAIT_TIMES[name])

def select_first_search_result(frame, hospital):
    print(f"Selecting: {hospital}")

    # Open the dropdown
    frame.click(DROPDOWN_SELECTOR, timeout=15000)
    debug_sleep("dropdown_sleep")

    # Type + Enter in search box
    search_box = frame.locator(SEARCH_BAR_SELECTOR)
    search_box.fill(hospital)
    search_box.press("Enter")
    debug_sleep("search_sleep")

    # Wait for slicer to show the hospital name in visible items
    frame.wait_for_selector(
        f'{SLICER_ITEM_SELECTOR} span.slicerText:text("{hospital}")',
        timeout=10000
    )

    # Click the container (not just the text span)
    frame.locator(SLICER_ITEM_SELECTOR).nth(0).click()
    debug_sleep("visual_update_sleep")

    # Optionally click away to commit
    try:
        frame.click("body", position={"x": 5, "y": 5})
        debug_sleep("visual_update_sleep")
    except:
        pass

    # Confirm final selection text
    selected = frame.locator(DROPDOWN_SELECTOR).inner_text().strip()
    if selected.lower() != hospital.lower():
        raise Exception(f"Dropdown shows '{selected}', expected '{hospital}'")
    else:
        print(f"Confirmed selection: {selected}")

def worker_task(hospitals_subset, output_dir, worker_id, run_timestamp):
    print(f"[Worker {worker_id}] Starting with {len(hospitals_subset)} hospital(s).")
    failed = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.goto(POWER_BI_URL, timeout=60000)

            # Determine correct frame
            try:
                page.wait_for_selector(IFRAME_SELECTOR, timeout=WAIT_TIMES["iframe_wait"] * 1000)
                iframe = page.frame_locator(IFRAME_SELECTOR)
                if iframe.locator(DROPDOWN_SELECTOR).count() == 0:
                    print(f"[Worker {worker_id}] Dropdown not in iframe — using main page.")
                    iframe = page
                else:
                    print(f"[Worker {worker_id}] Using iframe.")
            except Exception:
                print(f"[Worker {worker_id}] No iframe found, using main page.")
                iframe = page

            for hospital in hospitals_subset:
                try:
                    select_first_search_result(iframe, hospital)

                    safe_name = re.sub(r"[\\/*?:\"<>|]", "_", hospital)
                    pdf_name = f"SB_Report_{safe_name}_{run_timestamp}.pdf"
                    pdf_path = os.path.join(output_dir, pdf_name)

                    if ENABLE_SCREENSHOT:
                        screenshot_path = os.path.join(output_dir, f"{safe_name}_{run_timestamp}.png")
                        page.screenshot(path=screenshot_path, full_page=True)

                    page.pdf(path=pdf_path, print_background=True, format="A4")
                    print(f"[Worker {worker_id}] Saved {pdf_name}")
                except Exception as e:
                    print(f"[Worker {worker_id}] Failed for {hospital}: {e}")
                    failed.append(hospital)

            browser.close()
    except Exception as e:
        print(f"[Worker {worker_id}] Playwright error: {e}")
        return hospitals_subset

    return failed

def run_worker(args):
    return worker_task(*args)

# ---------------- Main Entry Point ----------------
if __name__ == "__main__":
    try:
        subprocess.run(["playwright", "install"], check=True)
    except Exception as e:
        sys.exit(f"Playwright installation failed: {e}")

    # Load hospitals
    try:
        with open(HOSPITALS_CSV, newline="") as f:
            hospitals = [row[0] for row in csv.reader(f) if row]
        if hospitals and hospitals[0].strip().lower() == "facility_name":
            hospitals = hospitals[1:]
    except Exception as e:
        sys.exit(f"Error reading hospitals CSV: {e}")

    # Timestamp and output folder
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join("data", "outputs", f"SB_Report_{run_timestamp}")
    os.makedirs(output_dir, exist_ok=True)

    # Select subset
    if TO_DEBUG:
        hospitals_to_process = hospitals[:1]
    else:
        try:
            num = input("How many hospitals? ('all' or number): ").strip()
            hospitals_to_process = hospitals if num.lower() == "all" else hospitals[:int(num)]
        except ValueError:
            hospitals_to_process = hospitals

    print(f"Processing {len(hospitals_to_process)} hospitals using {NUM_WORKERS} workers...")

    # Split work
    split_size = math.ceil(len(hospitals_to_process) / NUM_WORKERS)
    subsets = [hospitals_to_process[i:i + split_size] for i in range(0, len(hospitals_to_process), split_size)]
    args_list = [(subset, output_dir, i + 1, run_timestamp) for i, subset in enumerate(subsets)]

    # Execute workers
    failed = []
    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = [executor.submit(run_worker, args) for args in args_list]
        for future in as_completed(futures):
            failed.extend(future.result())

    # Save failed hospitals
    if failed:
        fail_csv = os.path.join(output_dir, "failed_hospitals.csv")
        with open(fail_csv, "w", newline="") as f:
            csv.writer(f).writerows([[h] for h in failed])
        print(f"Failed hospitals saved to {fail_csv}")
