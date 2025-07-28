import os
import re
import sys
import csv
import time
import math
import json
import subprocess
import unicodedata
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

# ---------------- Configuration ----------------
POWER_BI_URL = "https://app.powerbi.com/view?r=eyJrIjoiOTI0MWRlZDQtZTQ4OS00NjQyLWI1NTEtN2Y5NDZkOTc1ZGEzIiwidCI6ImM4MzU0YWFmLWVjYzUtNGZmNy05NTkwLWRmYzRmN2MxZjM2MSIsImMiOjEwfQ%3D%3D"
WAIT_TIMES = {
    "iframe_wait": 3,
    "dropdown_sleep": 3,
    "search_sleep": 3,
    "visual_update_sleep": 3
}
DROPDOWN_SELECTOR = ".slicer-restatement"
SEARCH_BAR_SELECTOR = "input.searchInput"
SLICER_ITEM_SELECTOR = "div.slicerItemContainer"
IFRAME_SELECTOR = "iframe[src*='powerbi']"
HOSPITALS_CSV = os.path.join("data", "inputs", "hospitals_new.csv")
TO_DEBUG = False
ENABLE_SCREENSHOT = False
NUM_WORKERS = 16
# ------------------------------------------------

def ensure_dependencies():
    try:
        import playwright
    except ImportError:
        print("Installing Playwright via pip...")
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)

    lockfile = os.path.join(os.path.expanduser("~"), ".playwright_installed")
    if not os.path.exists(lockfile):
        print("Installing Playwright browser binaries...")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        with open(lockfile, "w") as f:
            f.write("installed")

def debug_sleep(name):
    time.sleep(WAIT_TIMES[name])

def normalize_text(s):
    return " ".join(unicodedata.normalize("NFKC", s or "").strip().split())

def select_first_search_result(frame, hospital, screenshot_dir, screenshot_counter):
    if TO_DEBUG:
        print(f"Selecting: {hospital}")

    try:
        frame.click(DROPDOWN_SELECTOR, timeout=15000)
        debug_sleep("dropdown_sleep")
    except Exception:
        raise Exception("Failed to open dropdown.")

    try:
        search_box = frame.locator(SEARCH_BAR_SELECTOR)
        search_box.wait_for(state="visible", timeout=10000)
    except Exception:
        raise Exception("Search bar not visible.")

    try:
        search_box.fill(hospital)
        search_box.press("Enter")
    except Exception:
        if TO_DEBUG:
            print("[Retry] Refocusing dropdown and retrying search box fill...")
        frame.click(DROPDOWN_SELECTOR, timeout=5000)
        debug_sleep("dropdown_sleep")
        search_box = frame.locator(SEARCH_BAR_SELECTOR)
        search_box.wait_for(state="visible", timeout=5000)
        search_box.fill(hospital)
        search_box.press("Enter")

    debug_sleep("search_sleep")

    dropdown_items = frame.locator(SLICER_ITEM_SELECTOR)
    dropdown_items.first.wait_for(state="visible", timeout=10000)

    found = False
    count = dropdown_items.count()


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

    if not found:
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

    if not found:
        if ENABLE_SCREENSHOT:
            screenshot_path = os.path.join(screenshot_dir, f"{screenshot_counter:03d}.png")
            frame.page.screenshot(path=screenshot_path, full_page=True)
        raise Exception(f"No exact match found for '{hospital}' in dropdown")

    debug_sleep("visual_update_sleep")

    try:
        frame.click("body", position={"x": 5, "y": 5})
        debug_sleep("visual_update_sleep")
    except:
        pass

    selected = frame.locator(DROPDOWN_SELECTOR).inner_text().strip()
    if normalize_text(selected) != normalize_text(hospital):
        raise Exception(f"Dropdown shows '{selected}', expected '{hospital}'")
    elif TO_DEBUG:
        print(f"Confirmed selection: {selected}")

def worker_task(hospitals_subset, output_dir, worker_id, run_timestamp):
    from playwright.sync_api import sync_playwright

    if TO_DEBUG:
        print(f"[Worker {worker_id}] Starting with {len(hospitals_subset)} hospital(s).")
    failed = []
    screenshot_counter = 1

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(POWER_BI_URL, timeout=60000)

            try:
                page.wait_for_selector(IFRAME_SELECTOR, timeout=WAIT_TIMES["iframe_wait"] * 1000)
                iframe = page.frame_locator(IFRAME_SELECTOR)
                if iframe.locator(DROPDOWN_SELECTOR).count() == 0:
                    iframe = page
            except Exception:
                iframe = page

            for hospital in hospitals_subset:
                try:
                    select_first_search_result(iframe, hospital, output_dir, screenshot_counter)
                    screenshot_counter += 1

                    safe_name = re.sub(r"[\\/*?:\"<>|]", "_", hospital)
                    pdf_name = f"SB_Report_{run_timestamp}_{safe_name}.pdf"
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
        return hospitals_subset

    return failed

def run_worker(args):
    return worker_task(*args)

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.set_start_method("spawn", force=True)

    ensure_dependencies()

    try:
        with open(HOSPITALS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            hospitals = [normalize_text(row["faci_name"]) for row in reader if row.get("faci_name")]
    except Exception as e:
        sys.exit(f"Error reading hospitals_new.csv: {e}")

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join("data", "outputs", f"SB_Report_{run_timestamp}")
    os.makedirs(output_dir, exist_ok=True)

    try:
        num = input("How many hospitals? ('all' or number): ").strip()
        hospitals_to_process = hospitals if num.lower() == "all" else hospitals[:int(num)]
    except ValueError:
        hospitals_to_process = hospitals

    split_size = math.ceil(len(hospitals_to_process) / NUM_WORKERS)
    subsets = [hospitals_to_process[i:i + split_size] for i in range(0, len(hospitals_to_process), split_size)]
    args_list = [(subset, output_dir, i + 1, run_timestamp) for i, subset in enumerate(subsets)]

    failed = []
    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = [executor.submit(run_worker, args) for args in args_list]
        for future in as_completed(futures):
            failed.extend(future.result())

    if failed:
        fail_csv = os.path.join(output_dir, "failed_hospitals.csv")
        with open(fail_csv, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([[h] for h in failed])
        print(f"Failed hospitals saved to {fail_csv}")
