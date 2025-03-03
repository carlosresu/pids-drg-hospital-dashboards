import os
import re
import sys
import time
import json
import base64
import subprocess
import platform
import zipfile
import requests

from multiprocessing import Pool

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# -------------------------------------------------------------------
# 1) GLOBAL CONFIG
# -------------------------------------------------------------------

TO_DEBUG = True
MAX_RETRIES = 10

NUM_WORKERS_DEBUG = 1
NUM_WORKERS_NORMAL = 8

BIGQUERY_QUERY = "SELECT faci_name FROM `drg-viz.00_datasets.hci` ORDER BY faci_name ASC"
HOSPITALS_CSV = os.path.join("..", "data", "inputs", "hospitals.csv")
REPORTS_DIR = os.path.join("..", "data", "outputs")
FAILED_HOSPITALS = os.path.join("..", "data", "outputs", "failed_hospitals.csv")
WAIT_TIMES_JSON = os.path.join("..", "data", "cache", "final_wait_times.json")

POWER_BI_URL = (
    "https://app.powerbi.com/view?r=eyJrIjoiNDlmNjliNTUtOTEwOS00NTFhLWIwMGQtNzk1Y2VlYWIwNjBjIiwidCI6ImM4MzU0YWFmLWVjYzUtNGZmNy05NTkwLWRmYzRmN2MxZjM2MSIsImMiOjEwfQ%3D%3D"
)

# XPaths
IFRAME_XPATH = "//iframe[contains(@src, 'powerbi')]"
DROPDOWN_XPATH = "//div[@class='slicer-restatement']"
SEARCH_BAR_XPATH = "//input[@class='searchInput']"
FIRST_RESULT_XPATH = "(//span[@class='slicerText'])[1]"

# Step-specific wait times
WAIT_TIMES = {
    "iframe_wait": 1,
    "dropdown_sleep": 1,
    "search_sleep": 1,
    "visual_update_sleep": 1,
    "webdriver_wait_first_result": 1
}

# Chrome for Testing
CHROME_FOR_TESTING_JSON = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
DEFAULT_CHROME_PATHS = {
    "Windows": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "Darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "Linux": "/usr/bin/google-chrome",
}


# -------------------------------------------------------------------
# GCLOUD AUTH
# -------------------------------------------------------------------

def can_open_browser():
    sysname = platform.system()
    if sysname in ("Windows", "Darwin"):
        return True
    if sysname == "Linux":
        return bool(os.environ.get("DISPLAY"))
    return False

def _no_browser_auth():
    print("Attempting gcloud auth (no browser)...")
    # truncated for brevity

def authenticate_gcloud():
    if can_open_browser():
        # truncated for brevity
        pass
    else:
        _no_browser_auth()

def is_already_authenticated():
    try:
        client = bigquery.Client()
        client.query("SELECT 1").result()
        return True
    except Exception:
        return False

# -------------------------------------------------------------------
# CHROMEDRIVER
# -------------------------------------------------------------------

def get_default_chrome_path():
    sysname = platform.system()
    return DEFAULT_CHROME_PATHS.get(sysname)

def detect_local_chrome_version():
    # truncated for brevity
    return "133.0.6943.142"

def get_webdriver_path():
    # truncated for brevity
    # returns path to 'chromedriver'
    return "./chromedriver-mac-arm64/chromedriver"

# -------------------------------------------------------------------
# WORKER LOGIC
# -------------------------------------------------------------------

def worker_task(hospitals_subset, worker_id):
    """
    If any hospital fails => mark it as failed. 
    We'll gather them, and if >0 fail => entire run fails.
    """
    print(f"[Worker {worker_id}] Starting. Handling {len(hospitals_subset)} hospitals.")
    failed_list = []

    # 1) Launch Chrome
    try:
        driver_path = get_webdriver_path()
    except Exception as e:
        print(f"[Worker {worker_id}] Error obtaining driver: {e}")
        return hospitals_subset  # all fail

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")

    try:
        driver = webdriver.Chrome(service=Service(driver_path), options=options)
    except Exception as e:
        print(f"[Worker {worker_id}] Error launching Chrome: {e}")
        return hospitals_subset

    try:
        print(f"[Worker {worker_id}] Opening {POWER_BI_URL}")
        driver.get(POWER_BI_URL)

        # Attempt iframe
        try:
            WebDriverWait(driver, WAIT_TIMES["iframe_wait"]).until(
                EC.presence_of_element_located((By.XPATH, IFRAME_XPATH))
            )
            iframe = driver.find_element(By.XPATH, IFRAME_XPATH)
            driver.switch_to.frame(iframe)
            print(f"[Worker {worker_id}] Switched to iframe.")
        except Exception as ex:
            next

        os.makedirs(REPORTS_DIR, exist_ok=True)

        # For each hospital
        for hosp in hospitals_subset:
            print(f"[Worker {worker_id}] Selecting {hosp}")
            try:
                # 1) Click dropdown
                dropdown = driver.find_element(By.XPATH, DROPDOWN_XPATH)
                dropdown.click()
                time.sleep(WAIT_TIMES["dropdown_sleep"])

                # 2) Type hospital
                search_box = driver.find_element(By.XPATH, SEARCH_BAR_XPATH)
                search_box.clear()
                search_box.send_keys(hosp)
                time.sleep(WAIT_TIMES["search_sleep"])

                # 3) First result
                first_res = WebDriverWait(driver, WAIT_TIMES["webdriver_wait_first_result"]).until(
                    EC.element_to_be_clickable((By.XPATH, FIRST_RESULT_XPATH))
                )
                first_res.click()
                print(f"[Worker {worker_id}] Clicked first result for '{hosp}'.")

                # Wait visuals
                time.sleep(WAIT_TIMES["visual_update_sleep"])

                # Export PDF
                safe_name = re.sub(r'[\\/*?:"<>|]', "_", hosp)
                pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})
                pdf_path = os.path.join(REPORTS_DIR, f"{safe_name}.pdf")
                with open(pdf_path, "wb") as pdf_file:
                    pdf_file.write(base64.b64decode(pdf_data['data']))
                print(f"[Worker {worker_id}] Saved PDF as {pdf_path}.")

            except Exception as ex:
                print(f"[Worker {worker_id}] Hospital '{hosp}' failed: {ex}")
                failed_list.append(hosp)

    finally:
        driver.quit()

    return failed_list


# -------------------------------------------------------------------
# attempt_run (the entire pass)
# -------------------------------------------------------------------

def attempt_run():
    """
    1) Check auth
    2) Query BigQuery
    3) Prompt how many hospitals
    4) Distribute to workers
    5) If any fail => return False, else True
    """

    # Auth check
    if not is_already_authenticated():
        authenticate_gcloud()

    # Query BigQuery
    print(f"Querying BigQuery:\n{BIGQUERY_QUERY}")
    client = bigquery.Client()
    results = client.query(BIGQUERY_QUERY).result()
    hospital_names = [row.faci_name.strip() for row in results]
    total_count = len(hospital_names)
    if total_count == 0:
        print("No hospitals found. Aborting.")
        return True  # or False, depending on your logic

    # For simplicity, let's do a small subset (or prompt user)
    # e.g. only 2 hospitals for test
    chosen = hospital_names[:2]
    print(f"Will export for these hospitals: {chosen}")

    # Decide workers
    workers = NUM_WORKERS_DEBUG if TO_DEBUG else NUM_WORKERS_NORMAL

    # Round robin
    subsets = [[] for _ in range(workers)]
    for i, h in enumerate(chosen):
        subsets[i % workers].append(h)

    # Launch pool
    from multiprocessing import Pool
    with Pool(processes=workers) as pool:
        async_results = [pool.apply_async(worker_task, (subsets[w], w)) for w in range(workers)]
        pool.close()
        pool.join()

    # Gather fails
    all_fails = []
    for r in async_results:
        fails = r.get()
        if fails:
            all_fails.extend(fails)

    if all_fails:
        print(f"{len(all_fails)} hospitals failed => entire run fails.")
        return False
    else:
        print("All hospitals succeeded => run success.")
        return True
