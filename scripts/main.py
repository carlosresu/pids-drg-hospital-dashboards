import os
import re
import sys
import csv
import time
import math
import subprocess
import unicodedata
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

# ---------------- Configuration ----------------
# URL of the Power BI dashboard to be automated
POWER_BI_URL = "https://app.powerbi.com/view?r=eyJrIjoiOTI0MWRlZDQtZTQ4OS00NjQyLWI1NTEtN2Y5NDZkOTc1ZGEzIiwidCI6ImM4MzU0YWFmLWVjYzUtNGZmNy05NTkwLWRmYzRmN2MxZjM2MSIsImMiOjEwfQ%3D%3D"

# Wait times (in seconds) to control pacing for UI updates
WAIT_TIMES = {
    "iframe_wait": 3,            # Wait for iframe to load
    "dropdown_sleep": 3,         # Wait after opening dropdown
    "search_sleep": 3,           # Wait after searching
    "visual_update_sleep": 3     # Wait after selecting item
}

# Selectors for interacting with elements inside Power BI iframe
DROPDOWN_SELECTOR = ".slicer-restatement"       # Dropdown container
SEARCH_BAR_SELECTOR = "input.searchInput"       # Search input box
SLICER_ITEM_SELECTOR = "div.slicerItemContainer"# Each dropdown item
IFRAME_SELECTOR = "iframe[src*='powerbi']"      # Frame where dashboard loads

# Path to the fallback hospital CSV list (retry list)
HOSPITALS_CSV = os.path.join("data", "inputs", "failed_hospitals.csv")

# Global flags
TO_DEBUG = False                # Enable debug logging
ENABLE_SCREENSHOT = False       # Enable screenshot on failures
NUM_WORKERS = 4                 # Number of parallel workers
# ------------------------------------------------

# Ensure Playwright and Chromium are available for browser automation
def ensure_dependencies():
    import importlib.util

    def is_module_installed(module_name):
        return importlib.util.find_spec(module_name) is not None

    # Check if playwright is installed
    if not is_module_installed("playwright"):
        print("[Dependencies] Installing Playwright via pip...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=True)
            subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        except subprocess.CalledProcessError as e:
            sys.exit(f"[Error] Failed to install Playwright: {e}")

    # Install browser only once using a lockfile
    lockfile = os.path.join(os.path.expanduser("~"), ".playwright_installed_chromium")
    if not os.path.exists(lockfile):
        print("[Dependencies] Installing Chromium for Playwright...")
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            with open(lockfile, "w") as f:
                f.write("chromium_installed")
        except subprocess.CalledProcessError as e:
            sys.exit(f"[Error] Failed to install Chromium browser: {e}")
    else:
        print("[Dependencies] Chromium already installed. Skipping.")

# Wrapper around sleep to allow dynamic delays in debugging
def debug_sleep(name):
    time.sleep(WAIT_TIMES[name])

# Normalize and clean up text for comparison (remove whitespace, normalize characters)
def normalize_text(s):
    return " ".join(unicodedata.normalize("NFKC", s or "").strip().split())

# Interact with the dashboard to select a hospital from the dropdown
# This simulates typing and choosing from the dropdown filter
# Raises exceptions on failure, optionally takes screenshots

def select_first_search_result(frame, hospital, screenshot_dir, screenshot_counter):
    if TO_DEBUG:
        print(f"Selecting: {hospital}")

    # Open the dropdown with up to 2 retry attempts
    for attempt in range(2):
        try:
            frame.click(DROPDOWN_SELECTOR, timeout=15000)
            frame.wait_for_selector(SEARCH_BAR_SELECTOR, state="visible", timeout=10000)
            debug_sleep("dropdown_sleep")
            break
        except Exception as e:
            if attempt == 1:
                raise Exception(f"Failed to open dropdown: {e}")
            debug_sleep("dropdown_sleep")

    # Type hospital name in search bar
    try:
        search_box = frame.locator(SEARCH_BAR_SELECTOR)
        search_box.wait_for(state="visible", timeout=10000)
        search_box.fill(hospital)
        search_box.press("Enter")
    except Exception as e:
        raise Exception(f"Search input error: {e}")

    debug_sleep("search_sleep")
    dropdown_items = frame.locator(SLICER_ITEM_SELECTOR)

    # Ensure dropdown items loaded
    try:
        frame.wait_for_selector(f"{SLICER_ITEM_SELECTOR} span.slicerText", state="visible", timeout=10000)
        count = dropdown_items.count()
        if count == 0:
            raise Exception("Dropdown items failed to load.")
    except Exception as e:
        raise Exception(f"Dropdown wait error: {e}")

    # Try matching normalized text
    found = False
    count = dropdown_items.count()
    for i in range(count):
        item = dropdown_items.nth(i)
        try:
            text = item.locator("span.slicerText").inner_text().strip()
            if normalize_text(text) == normalize_text(hospital):
                item.click()
                found = True
                break
        except Exception:
            continue

    # Fallback to strict (non-normalized) match
    if not found:
        for i in range(count):
            item = dropdown_items.nth(i)
            try:
                text = item.locator("span.slicerText").inner_text().strip()
                if text == hospital:
                    item.click()
                    found = True
                    break
            except Exception:
                continue

    # If not found, optionally take screenshot and raise
    if not found:
        if ENABLE_SCREENSHOT:
            screenshot_path = os.path.join(screenshot_dir, f"{screenshot_counter:03d}.png")
            frame.page.screenshot(path=screenshot_path, full_page=True)
        raise Exception(f"No exact match found for '{hospital}' in dropdown")

    debug_sleep("visual_update_sleep")

    # Click outside to close dropdown
    try:
        frame.click("body", position={"x": 5, "y": 5})
        debug_sleep("visual_update_sleep")
    except:
        pass

    # Confirm selected hospital matches expectation
    try:
        selected = frame.locator(DROPDOWN_SELECTOR).inner_text().strip()
        if normalize_text(selected) != normalize_text(hospital):
            raise Exception(f"Dropdown shows '{selected}', expected '{hospital}'")
        elif TO_DEBUG:
            print(f"Confirmed selection: {selected}")
    except Exception as e:
        raise Exception(f"Post-selection verification error: {e}")

# Worker function to export PDF for a subset of hospitals
# Runs in separate subprocess via multiprocessing

def worker_task(hospitals_subset, output_dir, worker_id, run_timestamp):
    from playwright.sync_api import sync_playwright

    if TO_DEBUG:
        print(f"[Worker {worker_id}] Starting with {len(hospitals_subset)} hospital(s).")
    failed = []
    screenshot_counter = 1
    date_for_filename = run_timestamp.split("_")[0]  # YYYYMMDD only

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(POWER_BI_URL, timeout=60000)

            # Try locating iframe; fallback to full page if iframe fails
            try:
                page.wait_for_selector(IFRAME_SELECTOR, timeout=WAIT_TIMES["iframe_wait"] * 1000)
                iframe = page.frame_locator(IFRAME_SELECTOR)
                if iframe.locator(DROPDOWN_SELECTOR).count() == 0:
                    iframe = page
            except Exception:
                iframe = page

            # Process each hospital in assigned subset
            for hospital in hospitals_subset:
                try:
                    select_first_search_result(iframe, hospital, output_dir, screenshot_counter)
                    screenshot_counter += 1

                    safe_name = re.sub(r"[\\/*?:\"<>|]", "_", hospital)
                    pdf_name = f"SB_Report_{date_for_filename}_{safe_name}.pdf"
                    pdf_path = os.path.join(output_dir, pdf_name)

                    if ENABLE_SCREENSHOT:
                        screenshot_path = os.path.join(output_dir, f"{safe_name}_{run_timestamp}.png")
                        page.screenshot(path=screenshot_path, full_page=True)

                    page.pdf(path=pdf_path, print_background=True, format="A4")

                    if TO_DEBUG:
                        print(f"[Worker {worker_id}] Saved {pdf_name}")
                except Exception as e:
                    print(f"[Worker {worker_id}] Failed for {hospital}: {e}")
                    failed.append(hospital)

            browser.close()
    except Exception as e:
        print(f"[Worker {worker_id}] Playwright error: {e}")
        return hospitals_subset  # Fail all if setup failed

    return failed

# Simple wrapper to support multiprocessing interface
def run_worker(args):
    return worker_task(*args)

# ---------------- Main Execution ----------------
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.set_start_method("spawn", force=True)  # Ensure Playwright compatibility

    ensure_dependencies()  # Check and install dependencies if needed

    base_input_csv = os.path.join("data", "inputs", "hospitals_new.csv")
    failed_input_csv = os.path.join("data", "inputs", "failed_hospitals.csv")

    attempt = 1
    run_timestamp = None
    output_dir = None

    # Retry loop: first try from main list, then retry from failed list
    while True:
        print(f"\n=== Attempt {attempt} ===")

        input_csv = base_input_csv if attempt == 1 else failed_input_csv

        try:
            with open(input_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                hospitals = [normalize_text(row["faci_name"]) for row in reader if row.get("faci_name")]
        except Exception as e:
            sys.exit(f"Error reading {input_csv}: {e}")

        if not hospitals:
            print("No hospitals left to process.")
            break

        # Initialize timestamp and output directory on first attempt
        if attempt == 1:
            run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.join("data", "outputs", f"SB_Report_{run_timestamp}")
            os.makedirs(output_dir, exist_ok=True)

        # Divide hospitals across workers
        split_size = math.ceil(len(hospitals) / NUM_WORKERS)
        subsets = [hospitals[i:i + split_size] for i in range(0, len(hospitals), split_size)]
        args_list = [(subset, output_dir, i + 1, run_timestamp) for i, subset in enumerate(subsets)]

        # Launch parallel workers
        failed = []
        with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = [executor.submit(run_worker, args) for args in args_list]
            for future in as_completed(futures):
                failed.extend(future.result())

        # Write failed list to file, or break if all succeeded
        if failed:
            with open(failed_input_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["faci_name"])
                writer.writerows([[h] for h in failed])
            print(f"{len(failed)} hospitals failed. Retrying with new list...")
            attempt += 1
        else:
            print("All hospitals processed successfully.")
            break