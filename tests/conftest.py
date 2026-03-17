import os
import shutil
import time
import yaml
import pytest
import asyncio
import logging
from playwright.async_api import async_playwright, Page, BrowserContext
from utils.data_reader import DataReader

RESULTS_DIR = "results"
ALLURE_RESULTS_DIR = os.path.join(RESULTS_DIR, "allure-results")
ALLURE_REPORT_DIR = os.path.join(RESULTS_DIR, "allure-report")
HTML_REPORT = os.path.join(RESULTS_DIR, "report.html")

MASTER_LOG = os.path.join(RESULTS_DIR, "test_execution.log")

# Ensure results directory exists
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(ALLURE_RESULTS_DIR, exist_ok=True)

# Global configuration for browser profiles
BROWSER_PROFILES_PATH = os.path.join("data", "browser_profiles.yaml")

def load_browser_profiles():
    if os.path.exists(BROWSER_PROFILES_PATH):
        with open(BROWSER_PROFILES_PATH, 'r') as f:
            return yaml.safe_load(f).get('profiles', {})
    return {}

BROWSER_PROFILES = load_browser_profiles()

def pytest_sessionstart(session):
    """
    Clears all test artifacts at the start of the execution session.
    Only the master process wipes directories to avoid race conditions during parallel runs.
    """
    worker_id = os.environ.get('PYTEST_XDIST_WORKER')
    if worker_id is not None and worker_id not in ['master', 'gw0']:
        return

    import shutil
    import time

    # Wipe the entire results directory contents
    if os.path.exists(RESULTS_DIR):
        for item in os.listdir(RESULTS_DIR):
            item_path = os.path.join(RESULTS_DIR, item)
            # We preserve the master log handle if it's open, but we truncate it
            if item == os.path.basename(MASTER_LOG):
                 try:
                     with open(item_path, 'w') as f: f.truncate(0)
                 except Exception: pass
                 continue
                 
            try:
                # Retry logic for Windows file locks
                for _ in range(5):
                    try:
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                        break
                    except Exception:
                        time.sleep(0.5)
            except Exception as e:
                print(f"Warning: Could not remove {item_path}: {e}")

    # Re-ensure base directories exist
    os.makedirs(ALLURE_RESULTS_DIR, exist_ok=True)

    # Explicitly clear file artifacts
    for file_art in [MASTER_LOG, HTML_REPORT]:
        if os.path.exists(file_art):
            try:
                os.remove(file_art)
            except Exception:
                pass


def pytest_addoption(parser):
    """Add CLI options for browser matrix."""
    parser.addoption(
        "--browser-profiles", 
        action="store", 
        default="chrome_latest",
        help="Comma-separated list of browser profiles from browser_profiles.yaml (e.g., chrome_latest,firefox_latest)"
    )

def pytest_generate_tests(metafunc):
    """
    Parameterize the test matrix.
    If 'browser_config' and 'scenario' are in the fixtures, we zip them 
    to ensure 2 Chrome + 1 Firefox distribution for the 3 products.
    """
    if "browser_config" in metafunc.fixturenames and "scenario" in metafunc.fixturenames:
        # Load 3 scenarios
        all_scenarios = DataReader.read_json("test_data.json")
        if len(all_scenarios) > 3:
            all_scenarios = all_scenarios[:3]
            
        # Define the exact browser mapping requested: Using Chrome for all for debugging
        requested_profiles = ["chrome_latest", "chrome_latest", "chrome_latest"]
        
        configs = []
        final_scenarios = []
        ids = []
        
        for i, profile_name in enumerate(requested_profiles):
            if i < len(all_scenarios):
                config = BROWSER_PROFILES.get(profile_name, {"browser": "chromium"}).copy()
                config['profile_name'] = profile_name
                configs.append(config)
                final_scenarios.append(all_scenarios[i])
                ids.append(f"{profile_name}-{all_scenarios[i]['test_name'].replace(' ', '_')}")
        
        metafunc.parametrize("browser_config, scenario", list(zip(configs, final_scenarios)), ids=ids, scope="function")

# Configure base logging (Console only by default at session level)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(MASTER_LOG, mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

@pytest.fixture(scope="function")
def test_result_dir(request):
    """Provides a dedicated directory for each test scenario's artifacts."""
    import re
    # Extract the unique test ID (e.g., "chrome_latest-Nike_Shoes_Search")
    test_id = request.node.callspec.id if hasattr(request.node, "callspec") else request.node.name
    clean_name = re.sub(r'[^\w\-_]', '_', test_id)
    
    scenario_dir = os.path.join(RESULTS_DIR, clean_name)
    os.makedirs(scenario_dir, exist_ok=True)
    return scenario_dir

@pytest.fixture(autouse=True, scope="function")
def test_logger(request, test_result_dir):
    """
    Dynamically attaches a file handler for each test to save logs into its dedicated folder.
    """
    log_file = os.path.join(test_result_dir, "test.log")
    
    # Create test-specific handler
    handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    handler.setLevel(logging.INFO)
    
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    
    # Also attach the log path to the request node for reporting visibility
    request.node.test_log_path = log_file
    
    yield
    
    # Cleanup: remove handler after test completion
    root_logger.removeHandler(handler)
    handler.close()

@pytest.fixture(scope="session")
def event_loop():
    """Manage the asynchronous event loop for the session."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="function")
def test_data():
    """Fixture to provide test data from JSON."""
    return DataReader.read_json("test_data.json")

@pytest.fixture(scope="function")
async def page_context(request, browser_config, test_result_dir):
    """
    Standard fixture for providing a clean page for each test.
    Now parameterized by browser_config to support the browser matrix.
    """
    # Screenshots are saved in a 'screenshots' subfolder within the scenario directory
    test_screenshot_dir = os.path.join(test_result_dir, "screenshots")
    os.makedirs(test_screenshot_dir, exist_ok=True)


    from playwright_stealth import Stealth
    
    async with async_playwright() as p:
        browser_type = getattr(p, browser_config.get("browser", "chromium"))
        
        # Launch Arguments
        launch_args = {
            "headless": os.getenv("HEADLESS", "false").lower() == "true",
            "args": ["--start-maximized", "--disable-blink-features=AutomationControlled"]
        }
        
        if "channel" in browser_config:
            launch_args["channel"] = browser_config["channel"]
        if "executable_path" in browser_config:
            launch_args["executable_path"] = browser_config["executable_path"]
            
        browser = await browser_type.launch(**launch_args)
        
        # Context Arguments
        context_args = {
            "no_viewport": True,
            "user_agent": browser_config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "permissions": ["geolocation"]
        }
        
        context = await browser.new_context(**context_args)
        page = await context.new_page()
        
        # Explicitly maximize for browsers that don't support --start-maximized (like Firefox/Webkit)
        if browser_config.get("browser") != "chromium":
            await page.set_viewport_size({"width": 1920, "height": 1080})
        
        # Apply Stealth Mode
        await Stealth().apply_stealth_async(page)
        
        # Attach the directory to the page object
        page.screenshot_dir = test_screenshot_dir
        
        yield page
        
        await context.close()
        await browser.close()

def pytest_sessionfinish(session, exitstatus):
    """
    Hook to generate Allure report after the test session finishes.
    Only runs on the master process to avoid conflicts during parallel execution.
    """
    worker_id = os.environ.get('PYTEST_XDIST_WORKER')
    if worker_id is not None and worker_id != 'master':
        return

    import subprocess

    print("\n" + "="*50)
    print("ALLURE REPORT GENERATION")
    print("="*50)
    
    try:
        # 1. Check if Allure CLI is installed
        subprocess.run(["allure", "--version"], capture_output=True, check=True)
        
        # 2. Generate the report into results/allure-report
        cmd = ["allure", "generate", ALLURE_RESULTS_DIR, "-o", ALLURE_REPORT_DIR, "--clean"]
        subprocess.run(cmd, check=True)
        
        print(f"SUCCESS: Report generated at: {os.path.abspath(ALLURE_REPORT_DIR)}")
        print(f"TIP: To view the report, run: allure open {ALLURE_REPORT_DIR}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("WARNING: Allure CLI (Command Line Interface) is not installed on this system.")
        print("   The raw data was saved to 'results/allure-results', but I couldn't build the HTML report.")
        print("   To fix this: 'scoop install allure' or 'choco install allure'.")
    
    print("="*50 + "\n")
