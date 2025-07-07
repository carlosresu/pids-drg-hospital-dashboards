# ---------------------- src/functions_v2.py ----------------------

import os
import re
import time
import base64
import subprocess
import platform
import zipfile
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Global constants
POWER_BI_URL = "https://app.powerbi.com/view?r=eyJrIjoiNDlmNjliNTUtOTEwOS00NTFhLWIwMGQtNzk1Y2VlYWIwNjBjIiwidCI6ImM4MzU0YWFmLWVjYzUtNGZmNy05NTkwLWRmYzRmN2MxZjM2MSIsImMiOjEwfQ%3D%3D"
DROPDOWN_XPATH = "//div[@class='slicer-restatement']"
SEARCH_BAR_XPATH = "//input[@class='searchInput']"
FIRST_RESULT_XPATH = "(//span[@class='slicerText'])[1]"
IFRAME_XPATH = "//iframe[contains(@src, 'powerbi')]"
WAIT_TIMES = {
    "iframe_wait": 5,
    "dropdown_sleep": 15,
    "search_sleep": 10,
    "visual_update_sleep": 15,
    "webdriver_wait_first_result": 15
}
DEFAULT_CHROME_PATHS = {
    "Windows": r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "Darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "Linux": "/usr/bin/google-chrome"
}
CHROME_FOR_TESTING_JSON = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"

def debug_sleep(step):
    time.sleep(WAIT_TIMES[step])

def select_first_search_result(driver, hospital):
    driver.find_element(By.XPATH, DROPDOWN_XPATH).click()
    debug_sleep("dropdown_sleep")
    box = driver.find_element(By.XPATH, SEARCH_BAR_XPATH)
    box.clear()
    box.send_keys(hospital)
    debug_sleep("search_sleep")
    WebDriverWait(driver, WAIT_TIMES["webdriver_wait_first_result"]).until(
        EC.element_to_be_clickable((By.XPATH, FIRST_RESULT_XPATH))
    ).click()

def get_default_chrome_path():
    override = os.environ.get("CHROME_PATH")
    if override and os.path.isfile(override):
        return override
    return DEFAULT_CHROME_PATHS.get(platform.system())

def detect_local_chrome_version(chrome_path=None):
    if not chrome_path:
        chrome_path = get_default_chrome_path()
    if not chrome_path or not os.path.isfile(chrome_path):
        raise FileNotFoundError(f"Chrome not found at expected path: {chrome_path}")

    output = subprocess.check_output([chrome_path, "--version"]).decode().strip()
    match = re.search(r"Google Chrome (\d+\.\d+\.\d+\.\d+)", output)
    if not match:
        raise ValueError(f"Could not parse Chrome version from output: {output}")
    return match.group(1)

def version_tuple(version_str):
    return tuple(map(int, version_str.split(".")))

def get_driver_platform():
    sysname = platform.system()
    machine = platform.machine().lower()
    if sysname == "Darwin":
        return "mac-arm64" if "arm" in machine else "mac-x64"
    return {"Windows": "win64", "Linux": "linux64"}.get(sysname)

def fetch_chrome_versions():
    return requests.get(CHROME_FOR_TESTING_JSON).json().get("versions", [])

def find_closest_version(all_versions, local_tuple):
    return min(all_versions, key=lambda v: sum(abs(a - b) for a, b in zip(version_tuple(v["version"]), local_tuple)))

def download_chromedriver(entry, platform_tag):
    for d in entry["downloads"].get("chromedriver", []):
        if d["platform"] == platform_tag:
            url = d["url"]
            zip_file = f"chromedriver_{platform_tag}.zip"
            print(f"Downloading ChromeDriver from {url}")
            with open(zip_file, "wb") as f:
                f.write(requests.get(url).content)
            with zipfile.ZipFile(zip_file, "r") as z:
                z.extractall(".")
            os.remove(zip_file)
            path = os.path.join(f"chromedriver-{platform_tag}", "chromedriver")
            os.chmod(path, 0o755)
            return path
    raise RuntimeError("No matching ChromeDriver found.")

def ensure_driver_present():
    """Checks if driver already downloaded, if not, downloads it."""
    driver_platform = get_driver_platform()
    extracted_dir = f"chromedriver-{driver_platform}"
    driver_path = os.path.join(extracted_dir, "chromedriver")
    if os.path.isfile(driver_path):
        return driver_path
    print("ChromeDriver not found locally. Downloading...")
    local_ver = detect_local_chrome_version()
    all_versions = fetch_chrome_versions()
    closest = find_closest_version(all_versions, version_tuple(local_ver))
    return download_chromedriver(closest, driver_platform)

def worker_task(hospitals_subset, output_dir, worker_id, driver_path=None):
    print(f"[Worker {worker_id}] Starting with {len(hospitals_subset)} hospital(s).")
    try:
        if not driver_path:
            driver_path = os.environ.get("WEBDRIVER_PATH") or ensure_driver_present()
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(service=Service(driver_path), options=options)
    except Exception as e:
        print(f"[Worker {worker_id}] Failed to start Chrome: {e}")
        return hospitals_subset

    failed = []
    try:
        driver.get(POWER_BI_URL)
        try:
            WebDriverWait(driver, WAIT_TIMES["iframe_wait"]).until(
                EC.presence_of_element_located((By.XPATH, IFRAME_XPATH))
            )
            driver.switch_to.frame(driver.find_element(By.XPATH, IFRAME_XPATH))
        except Exception:
            print(f"[Worker {worker_id}] No iframe detected.")

        for hospital in hospitals_subset:
            try:
                select_first_search_result(driver, hospital)
                debug_sleep("visual_update_sleep")
                safe_name = re.sub(r"[\\/*?:\"<>|]", "_", hospital)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                pdf_name = f"SB_Report_{safe_name}_{timestamp}.pdf"
                pdf_path = os.path.join(output_dir, pdf_name)
                pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})
                with open(pdf_path, "wb") as f:
                    f.write(base64.b64decode(pdf_data["data"]))
                print(f"[Worker {worker_id}] Saved {pdf_name}")
            except Exception as e:
                print(f"[Worker {worker_id}] Failed for {hospital}: {e}")
                failed.append(hospital)
    finally:
        driver.quit()

    return failed