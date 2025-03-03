"""
source-chrome-webdriver.py

This module provides a function to:
1) Detect the local Chrome version.
2) Find the closest matching ChromeDriver from the Chrome for Testing feed.
3) Skip download if the extracted driver folder already exists, otherwise download & unzip it.
4) Remove the .zip file after extraction.
5) Return the path to the 'chromedriver' binary.

Usage (in another script):
    from source_chrome_webdriver import get_webdriver_path
    driver_path = get_webdriver_path()
"""

import os
import re
import sys
import zipfile
import platform
import subprocess
import requests

# URL for the Chrome for Testing JSON feed
CHROME_FOR_TESTING_JSON = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"

# Default Chrome paths by OS
DEFAULT_CHROME_PATHS = {
    "Windows": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "Darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
    "Linux": "/usr/bin/google-chrome",
}


def get_default_chrome_path():
    """
    Return a default Chrome path based on OS, or None if unknown.
    """
    system = platform.system()
    return DEFAULT_CHROME_PATHS.get(system)


def detect_local_chrome_version(chrome_path=None):
    """
    Run '<chrome_path> --version' and parse the output like:
      "Google Chrome 113.0.5672.63" -> "113.0.5672.63"
    Raises FileNotFoundError if Chrome isn't found, ValueError if unparseable.
    """
    if not chrome_path:
        chrome_path = get_default_chrome_path()
    if not chrome_path or not os.path.isfile(chrome_path):
        raise FileNotFoundError("Chrome not found at default path. Please specify or install Chrome.")

    output = subprocess.check_output([chrome_path, "--version"]).decode("utf-8").strip()
    match = re.search(r"Google Chrome (\d+\.\d+\.\d+\.\d+)", output)
    if not match:
        raise ValueError(f"Could not parse Chrome version from: {output}")

    return match.group(1)


def version_tuple(version_str):
    """
    Convert a version like '113.0.5672.63' -> (113, 0, 5672, 63)
    for easy comparison or distance metrics.
    """
    return tuple(map(int, version_str.split(".")))


def get_driver_platform():
    """
    Return one of: 'mac-arm64', 'mac-x64', 'win64', 'linux64'
    based on the OS and CPU architecture.
    """
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Darwin":
        if "arm" in machine:
            return "mac-arm64"
        else:
            return "mac-x64"
    elif system == "Windows":
        return "win64"
    elif system == "Linux":
        return "linux64"
    else:
        raise NotImplementedError(f"Unsupported OS: {system}")


def fetch_chrome_for_testing_versions():
    """
    Fetch and parse the known-good-versions-with-downloads.json feed,
    returning a list of version entries.
    """
    resp = requests.get(CHROME_FOR_TESTING_JSON)
    resp.raise_for_status()
    data = resp.json()
    return data.get("versions", [])


def find_closest_version_entry(all_versions, local_ver_tuple):
    """
    Among the version entries, pick the one with minimal distance
    from the local Chrome version.
    """
    closest_entry = None
    closest_dist = None

    for entry in all_versions:
        ver_str = entry["version"]  # e.g. "113.0.5672.63"
        ver_tuple_ = version_tuple(ver_str)
        dist = sum(abs(a - b) for a, b in zip(ver_tuple_, local_ver_tuple))

        if closest_entry is None or dist < closest_dist:
            closest_entry = entry
            closest_dist = dist

    return closest_entry


def download_and_unzip_chromedriver(entry, driver_platform):
    """
    Given an entry (with "downloads" array) and a platform (e.g. 'mac-arm64'),
    find the correct chromedriver URL, skip download if the extracted folder already exists,
    otherwise download & unzip it, remove the .zip, and return the path to 'chromedriver'.
    """
    # 1) Find the matching platform download
    driver_info = None
    for d in entry["downloads"].get("chromedriver", []):
        if d["platform"] == driver_platform:
            driver_info = d
            break
    if not driver_info:
        raise RuntimeError(
            f"No matching ChromeDriver for version={entry['version']} platform={driver_platform}"
        )

    # We'll store the extracted folder as "chromedriver-<driver_platform>"
    extracted_dir_name = f"chromedriver-{driver_platform}"
    driver_path = os.path.join(extracted_dir_name, "chromedriver")

    # 2) Check if we already have the extracted folder
    if os.path.isdir(extracted_dir_name):
        print(f"Directory '{extracted_dir_name}' already exists. Skipping download.")
    else:
        # 3) Download the zip
        url = driver_info["url"]
        zip_filename = f"chromedriver_{driver_platform}.zip"
        print(f"Downloading ChromeDriver from: {url}")
        with open(zip_filename, "wb") as f:
            f.write(requests.get(url).content)

        # 4) Unzip
        with zipfile.ZipFile(zip_filename, "r") as zf:
            zf.extractall(".")
        print(f"Extracted contents of '{zip_filename}' to current directory.")

        # 5) Remove the zip file
        try:
            os.remove(zip_filename)
            print(f"Removed '{zip_filename}' after extraction.")
        except OSError as e:
            print(f"Warning: Could not remove '{zip_filename}': {e}")

    # 6) Verify that 'chromedriver' binary exists
    if not os.path.isfile(driver_path):
        raise RuntimeError(
            f"chromedriver binary not found at '{driver_path}'. "
            f"Check if the folder name or structure has changed."
        )

    # 7) Make it executable
    os.chmod(driver_path, 0o755)
    print(f"ChromeDriver ready at: {driver_path}")

    return driver_path


def get_webdriver_path():
    """
    Main helper function to:
      - Detect local Chrome version
      - Find closest version in Chrome for Testing feed
      - Skip re-download if the folder is present, else download & unzip
      - Return the path to 'chromedriver'
    """
    # 1) Detect local Chrome
    local_ver_str = detect_local_chrome_version()
    local_tuple = version_tuple(local_ver_str)
    print(f"Local Chrome version: {local_ver_str}")

    # 2) Determine platform
    driver_platform = get_driver_platform()
    print(f"Detected driver platform: {driver_platform}")

    # 3) Fetch all known-good versions
    all_versions = fetch_chrome_for_testing_versions()
    if not all_versions:
        sys.exit("No versions found in Chrome for Testing feed.")

    # 4) Find closest version entry
    closest_entry = find_closest_version_entry(all_versions, local_tuple)
    print(f"Closest known-good version to {local_ver_str} is {closest_entry['version']}")

    # 5) Download/unzip if needed, then return path
    driver_path = download_and_unzip_chromedriver(closest_entry, driver_platform)
    return driver_path
