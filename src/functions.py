"""
Contains:
 - Global configuration toggles (TO_DEBUG, WAIT_TIMES, etc.)
 - GCLOUD auth helpers
 - ChromeDriver detection
 - Worker logic (worker_task)
 - The adaptive wait logic (debug_retry_step, debug_sleep)
 - Slicer selection logic (select_first_search_result)
 - Overall attempt_run() and StepFailure for adaptive wait testing
"""

# -------------------------------------------------------
# Standard Library Imports
# -------------------------------------------------------
import os
import re
import sys
import time
import csv
import base64
import subprocess
import platform
import zipfile
import requests
import math  # For splitting hospitals among workers
from concurrent.futures import ProcessPoolExecutor, as_completed  # For parallel workers

# -------------------------------------------------------
# Third-Party Imports
# -------------------------------------------------------
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# -------------------------------------------------------
# 1) GLOBAL CONFIG / TOGGLES
# -------------------------------------------------------

TO_DEBUG = True
MAX_RETRIES = 10

NUM_WORKERS_DEBUG = 1
NUM_WORKERS_NORMAL = 8

BIGQUERY_QUERY = "SELECT faci_name FROM `drg-viz.00_datasets.hci` ORDER BY faci_name ASC"

HOSPITALS_CSV = os.path.join("..", "data", "inputs", "hospitals.csv")
REPORTS_DIR = os.path.join("..", "data", "outputs")
FAILED_HOSPITALS = os.path.join("..", "data", "outputs", "failed_hospitals.csv")

POWER_BI_URL = (
    "https://app.powerbi.com/view?"
    "r=eyJrIjoiNDlmNjliNTUtOTEwOS00NTFhLWIwMGQtNzk1Y2VlYWIwNjBjIiwidCI6ImM4MzU0"
    "YWFmLWVjYzUtNGZmNy05NTkwLWRmYzRmN2MxZjM2MSIsImMiOjEwfQ%3D%3D"
)

# Short XPaths for Selenium operations
DROPDOWN_XPATH = "//div[@class='slicer-restatement']"
SEARCH_BAR_XPATH = "//input[@class='searchInput']"
FIRST_RESULT_XPATH = "(//span[@class='slicerText'])[1]"
IFRAME_XPATH = "//iframe[contains(@src, 'powerbi')]"

# Step-specific wait times for each step (in seconds)
WAIT_TIMES = {
    "iframe_wait": 1,
    "dropdown_sleep": 1,
    "search_sleep": 1,
    "visual_update_sleep": 1,
    "webdriver_wait_first_result": 1
}

# -------------------------------------------------------
# CHROME FOR TESTING
# -------------------------------------------------------

CHROME_FOR_TESTING_JSON = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
DEFAULT_CHROME_PATHS = {
    "Windows": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "Darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "Linux": "/usr/bin/google-chrome",
}

# -------------------------------------------------------
# GCLOUD AUTH HELPERS
# -------------------------------------------------------

def can_open_browser():
    sysname = platform.system()
    if sysname in ("Windows", "Darwin"):
        return True
    if sysname == "Linux":
        return bool(os.environ.get("DISPLAY"))
    return False

def _no_browser_auth():
    print("Attempting gcloud authentication with no browser...")
    proc = subprocess.Popen(
        ["gcloud", "auth", "application-default", "login", "--no-launch-browser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        text=True
    )
    link_found = False
    for line in proc.stdout:
        if "Go to the following link" in line:
            link_found = True
            continue
        if link_found and line.strip().startswith("http"):
            link = line.strip()
            link_found = False
            print(f"\nOpen this link in your browser:\n{link}\n")
            input("Press Enter once you've opened the link and logged in... ")
            verification_code = input("Paste the verification code here: ").strip()
            proc.stdin.write(verification_code + "\n")
            proc.stdin.flush()
            continue
    proc.wait()
    if proc.returncode == 0:
        print("gcloud authentication successful (no-browser).")
    else:
        print(f"Error: gcloud authentication failed with return code {proc.returncode}")

def authenticate_gcloud():
    if can_open_browser():
        print("Detected local browser. Attempting normal gcloud login...")
        proc = subprocess.run(
            ["gcloud", "auth", "application-default", "login"],
            capture_output=True,
            text=True
        )
        if proc.returncode == 0:
            print("gcloud authentication successful (local browser).")
        else:
            print("gcloud auth failed, fallback to no-browser approach.\n")
            _no_browser_auth()
    else:
        print("No local browser detected, using no-browser approach.")
        _no_browser_auth()

def is_already_authenticated():
    try:
        client = bigquery.Client()
        client.query("SELECT 1").result()
        return True
    except Exception as e:
        print(f"[DEBUG] Authentication test failed: {e}")
        return False

# -------------------------------------------------------
# CHROMEDRIVER DETECTION
# -------------------------------------------------------

def get_default_chrome_path():
    sysname = platform.system()
    return DEFAULT_CHROME_PATHS.get(sysname)

def detect_local_chrome_version(chrome_path=None):
    if not chrome_path:
        chrome_path = get_default_chrome_path()
    if not chrome_path or not os.path.isfile(chrome_path):
        raise FileNotFoundError("Chrome not found at default path.")
    output = subprocess.check_output([chrome_path, "--version"]).decode("utf-8").strip()
    match = re.search(r"Google Chrome (\d+\.\d+\.\d+\.\d+)", output)
    if not match:
        raise ValueError(f"Could not parse Chrome version from: {output}")
    return match.group(1)

def version_tuple(version_str):
    return tuple(map(int, version_str.split(".")))

def get_driver_platform():
    sysname = platform.system()
    machine = platform.machine().lower()
    if sysname == "Darwin":
        return "mac-arm64" if "arm" in machine else "mac-x64"
    elif sysname == "Windows":
        return "win64"
    elif sysname == "Linux":
        return "linux64"
    else:
        raise NotImplementedError(f"Unsupported OS: {sysname}")

def fetch_chrome_for_testing_versions():
    resp = requests.get(CHROME_FOR_TESTING_JSON)
    resp.raise_for_status()
    data = resp.json()
    return data.get("versions", [])

def find_closest_version_entry(all_versions, local_ver_tuple):
    closest_entry = None
    closest_dist = None
    for entry in all_versions:
        ver_str = entry["version"]
        ver_tuple_ = version_tuple(ver_str)
        dist = sum(abs(a - b) for a, b in zip(ver_tuple_, local_ver_tuple))
        if closest_entry is None or dist < closest_dist:
            closest_entry = entry
            closest_dist = dist
    return closest_entry

def download_and_unzip_chromedriver(entry, driver_platform):
    driver_info = None
    for d in entry["downloads"].get("chromedriver", []):
        if d["platform"] == driver_platform:
            driver_info = d
            break
    if not driver_info:
        raise RuntimeError("No matching ChromeDriver found.")
    extracted_dir_name = f"chromedriver-{driver_platform}"
    driver_path = os.path.join(extracted_dir_name, "chromedriver")
    if os.path.isdir(extracted_dir_name):
        print(f"Directory '{extracted_dir_name}' already exists. Skipping download.")
    else:
        url = driver_info["url"]
        zip_filename = f"chromedriver_{driver_platform}.zip"
        print(f"Downloading ChromeDriver from: {url}")
        with open(zip_filename, "wb") as f:
            f.write(requests.get(url).content)
        with zipfile.ZipFile(zip_filename, "r") as zf:
            zf.extractall(".")
        print(f"Extracted '{zip_filename}'.")
        try:
            os.remove(zip_filename)
        except OSError as e:
            print(f"Warning: Could not remove '{zip_filename}': {e}")
    if not os.path.isfile(driver_path):
        raise RuntimeError(f"chromedriver not found at '{driver_path}'.")
    os.chmod(driver_path, 0o755)
    print(f"ChromeDriver ready at: {driver_path}")
    return driver_path

def get_webdriver_path():
    local_ver_str = detect_local_chrome_version()
    local_tuple = version_tuple(local_ver_str)
    print(f"Local Chrome version: {local_ver_str}")
    driver_platform = get_driver_platform()
    print(f"Detected driver platform: {driver_platform}")
    all_versions = fetch_chrome_for_testing_versions()
    if not all_versions:
        sys.exit("No versions found in Chrome for Testing feed.")
    closest_entry = find_closest_version_entry(all_versions, local_tuple)
    print(f"Closest known-good version to {local_ver_str} is {closest_entry['version']}")
    return download_and_unzip_chromedriver(closest_entry, driver_platform)

# -------------------------------------------------------
# ADAPTIVE WAIT LOGIC
# -------------------------------------------------------

def debug_retry_step(step_name, func, *args, **kwargs):
    """
    Try the given step once. If it fails due to a TimeoutException or NoSuchElementException,
    and TO_DEBUG is True, print the error and immediately raise a StepFailure to trigger a full restart.
    """
    try:
        return func(*args, **kwargs)
    except (TimeoutException, NoSuchElementException) as ex:
        if TO_DEBUG:
            print(f"[DEBUG] Step '{step_name}' failed with error: {ex}")
            raise StepFailure(step_name) from ex
        else:
            raise

def debug_sleep(step_name):
    time.sleep(WAIT_TIMES[step_name])

# -------------------------------------------------------
# SLICER SELECTION
# -------------------------------------------------------

def select_first_search_result(driver, hospital):
    dropdown_el = debug_retry_step("dropdown_sleep", driver.find_element, By.XPATH, DROPDOWN_XPATH)
    dropdown_el.click()
    debug_sleep("dropdown_sleep")
    search_box = debug_retry_step("search_sleep", driver.find_element, By.XPATH, SEARCH_BAR_XPATH)
    search_box.clear()
    search_box.send_keys(hospital)
    debug_sleep("search_sleep")
    first_result = WebDriverWait(driver, WAIT_TIMES["webdriver_wait_first_result"]).until(
        EC.element_to_be_clickable((By.XPATH, FIRST_RESULT_XPATH))
    )
    first_result.click()
    print(f"Clicked first search result for '{hospital}'.")

# -------------------------------------------------------
# WORKER TASK
# -------------------------------------------------------

def worker_task(hospitals_subset, worker_id):
    """
    Process each hospital in the provided subset:
      - Switch to the Power BI iframe if available.
      - Select the hospital via the slicer.
      - Wait for visual update.
      - Export the view to PDF.
    In debug mode, any failure is propagated immediately.
    In non-debug mode, failures are collected.
    """
    print(f"[Worker {worker_id}] Starting. Handling {len(hospitals_subset)} hospitals.")
    failed_list = []
    try:
        driver_path = get_webdriver_path()
    except Exception as e:
        print(f"[Worker {worker_id}] Error obtaining ChromeDriver path: {e}")
        return hospitals_subset

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    service = Service(driver_path)
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"[Worker {worker_id}] Error launching Chrome: {e}")
        return hospitals_subset

    try:
        print(f"[Worker {worker_id}] Navigating to Power BI report: {POWER_BI_URL}")
        driver.get(POWER_BI_URL)
        try:
            WebDriverWait(driver, WAIT_TIMES["iframe_wait"]).until(
                EC.presence_of_element_located((By.XPATH, IFRAME_XPATH))
            )
            iframe = driver.find_element(By.XPATH, IFRAME_XPATH)
            driver.switch_to.frame(iframe)
            print(f"[Worker {worker_id}] Switched to the Power BI iframe.")
        except (TimeoutException, NoSuchElementException) as ex:
            print(f"[Worker {worker_id}] No iframe found or timed out. Error: {ex}")
        os.makedirs(REPORTS_DIR, exist_ok=True)
        for hospital in hospitals_subset:
            print(f"[Worker {worker_id}] Selecting hospital: {hospital}")
            if TO_DEBUG:
                # In debug mode, let any exception (e.g. from debug_retry_step) propagate.
                select_first_search_result(driver, hospital)
            else:
                try:
                    select_first_search_result(driver, hospital)
                except Exception as ex:
                    print(f"[Worker {worker_id}] Warning: '{hospital}' error. Skipping. {ex}")
                    failed_list.append(hospital)
                    try:
                        driver.find_element(By.TAG_NAME, "body").click()
                    except Exception:
                        pass
                    continue

            debug_sleep("visual_update_sleep")
            try:
                safe_name = re.sub(r'[\\/*?:"<>|]', "_", hospital)
                pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})
                pdf_path = os.path.join(REPORTS_DIR, f"{safe_name}.pdf")
                with open(pdf_path, "wb") as pdf_file:
                    pdf_file.write(base64.b64decode(pdf_data['data']))
                print(f"[Worker {worker_id}] Saved PDF as '{pdf_path}'.")
            except Exception as e:
                if TO_DEBUG:
                    # In debug mode, propagate the error immediately.
                    raise e
                else:
                    print(f"[Worker {worker_id}] Error saving PDF for '{hospital}': {e}")
                    failed_list.append(hospital)
        print(f"[Worker {worker_id}] Done exporting {len(hospitals_subset)} PDFs.")
    finally:
        driver.quit()

    return failed_list

# -------------------------------------------------------
# ATTEMPT RUN FUNCTION AND STEP FAILURE EXCEPTION
# -------------------------------------------------------

class StepFailure(Exception):
    def __init__(self, step_name):
        self.step_name = step_name
        super().__init__(f"Step failure at {step_name}")

def attempt_run():
    """
    Attempt the complete process:
      - Read hospitals from CSV.
      - In debug mode, automatically process 5 hospitals and force 1 worker.
      - Otherwise, ask the user for the number of hospitals and workers.
      - Run the worker task.
      - In debug mode, any failure will propagate via a StepFailure.
      - In non-debug mode, if failures occur, append them to FAILED_HOSPITALS and raise StepFailure.
    """
    try:
        with open(HOSPITALS_CSV, newline="") as csvfile:
            reader = csv.reader(csvfile)
            hospitals = [row[0] for row in reader if row]
        print(f"Loaded {len(hospitals)} entries from {HOSPITALS_CSV}.")
    except Exception as e:
        print(f"Error reading hospitals CSV: {e}")
        raise StepFailure("read_csv")
    
    if hospitals and hospitals[0].strip().lower() == "facility_name":
        hospitals = hospitals[1:]
        print("Skipped header row in CSV.")
    
    if TO_DEBUG:
        hospitals = hospitals[:1]
        print("TO_DEBUG is True; processing 5 hospitals automatically.")
        num_workers = 1
    else:
        num_hospitals_input = input("How many hospitals do you want to download PDFs for? (Enter number or 'all'): ").strip()
        if num_hospitals_input.lower() == "all":
            num_hospitals = len(hospitals)
        else:
            try:
                num_hospitals = int(num_hospitals_input)
            except ValueError:
                print("Invalid input. Using all hospitals.")
                num_hospitals = len(hospitals)
        hospitals = hospitals[:num_hospitals]
        print(f"Processing {len(hospitals)} hospitals.")
        num_workers_input = input("Enter number of workers to use: ").strip()
        try:
            num_workers = int(num_workers_input)
        except ValueError:
            print("Invalid input. Using default number of workers.")
            num_workers = NUM_WORKERS_NORMAL

    if num_workers == 1:
        failed = worker_task(hospitals, worker_id=1)
    else:
        split_size = math.ceil(len(hospitals) / num_workers)
        hospitals_subsets = [hospitals[i:i+split_size] for i in range(0, len(hospitals), split_size)]
        failed = []
        print(f"Using {num_workers} workers to process {len(hospitals)} hospitals.")
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(worker_task, subset, i+1): subset for i, subset in enumerate(hospitals_subsets)}
            for future in as_completed(futures):
                failed.extend(future.result())
    
    if failed and not TO_DEBUG:
        print(f"Failed hospitals: {failed}")
        try:
            with open(FAILED_HOSPITALS, "a", newline="") as csvfile:
                writer = csv.writer(csvfile)
                for hospital in failed:
                    writer.writerow([hospital])
            print(f"Appended failed hospitals to {FAILED_HOSPITALS}.")
        except Exception as e:
            print(f"Error writing failed hospitals CSV: {e}")
        raise StepFailure("worker_task")
    elif failed and TO_DEBUG:
        # In debug mode, if any failure occurs, propagate the exception.
        raise StepFailure("dropdown_sleep")
    return True