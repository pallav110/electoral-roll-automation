import os
import time
import zipfile
import base64
import json
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

OUTPUT_FOLDER = "downloaded_pdfs"
BASE_URL = "https://voters.eci.gov.in/download-eroll"
CAPTCHA_PATH = "captcha.png"

# Vision API configuration
VISION_API_URL = "https://api.nvidia.com/v1/chat/completions"
VISION_MODEL = "nvidia/meta/llama-3.2-11b-vision-instruct"

class ECIDownloader:
    def __init__(self, vision_api_key=None):
        if not os.path.exists(OUTPUT_FOLDER):
            os.makedirs(OUTPUT_FOLDER)
        # Use provided key or fall back to environment variable
        self.vision_api_key = vision_api_key or os.environ.get("VISION_API_KEY")
        self.downloaded_files = []

    def solve_captcha_with_vision(self, image_path):
        """Use vision model to solve captcha."""
        print(f"[*] Analyzing {image_path} with vision model...")

        if not self.vision_api_key:
            print("[!] No vision API key provided")
            return "MANUAL"

        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            headers = {
                "Authorization": f"Bearer {self.vision_api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Read the captcha code from this image. Return ONLY the alphanumeric code, nothing else."
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_data}"}
                            }
                        ]
                    }
                ],
                "max_tokens": 50,
                "temperature": 0
            }

            response = requests.post(VISION_API_URL, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()
                captcha_code = result['choices'][0]['message']['content'].strip()
                print(f"[*] Vision model returned: {captcha_code}")
                return captcha_code
            else:
                print(f"[!] Vision API error: {response.status_code}")
        except Exception as e:
            print(f"[!] Vision model error: {e}")

        return "MANUAL"

    def discover_all_options(self):
        """Discover all states, years, roll types, districts, constituencies, languages"""
        print("[*] Discovering all dropdown options...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # Use visible mode for discovery
            context = browser.new_context()
            page = context.new_page()
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            time.sleep(2)  # Extra wait for page to fully load

            # Get all states
            state_select = page.locator("#stateCode")
            state_options = state_select.locator("option").all()
            states = []
            for opt in state_options:
                val = opt.get_attribute("value")
                text = opt.inner_text().strip()
                if val and val != "":
                    states.append({"value": val, "label": text})

            all_data = {}

            for state in states:
                print(f"  Discovering: {state['label']} ({state['value']})")
                page.select_option("#stateCode", value=state['value'])
                page.wait_for_load_state("networkidle")
                time.sleep(1)

                # Get years
                year_select = page.locator("#revyear")
                year_options = year_select.locator("option").all()
                years = []
                for opt in year_options:
                    val = opt.get_attribute("value")
                    text = opt.inner_text().strip()
                    if val and val != "":
                        years.append({"value": val, "label": text})

                state_data = {"years": {}}

                for year in years:
                    page.select_option("#revyear", value=year['value'])
                    page.wait_for_load_state("networkidle")
                    time.sleep(1)

                    # Check for alerts
                    alerts = page.locator(".library-alert, .alert").all()
                    has_alert = False
                    for alert in alerts:
                        alert_text = alert.inner_text()
                        if "not available" in alert_text.lower() or "warning" in alert_text.lower():
                            has_alert = True

                    if has_alert:
                        continue

                    # Get Roll Types
                    try:
                        page.wait_for_selector("#roleType", state="attached", timeout=5000)
                        roll_select = page.locator("#roleType")
                        roll_options = roll_select.locator("option").all()
                        roll_types = []
                        for opt in roll_options:
                            val = opt.get_attribute("value")
                            text = opt.inner_text().strip()
                            if val and val != "":
                                roll_types.append({"value": val, "label": text})
                    except:
                        roll_types = []

                    year_data = {"roll_types": {}}

                    for roll_type in roll_types:
                        print(f"    Selecting roll type: {roll_type['label']}")
                        # Use value instead of label for more reliable matching
                        page.select_option("#roleType", value=roll_type['value'])
                        page.wait_for_load_state("networkidle")
                        time.sleep(1)  # Wait for AJAX to load districts

                        # Get Districts
                        try:
                            page.wait_for_selector("#district", state="visible", timeout=10000)
                            dist_select = page.locator("#district")
                            dist_options = dist_select.locator("option").all()
                            districts = []
                            for opt in dist_options:
                                val = opt.get_attribute("value")
                                text = opt.inner_text().strip()
                                if val and val != "":
                                    districts.append({"value": val, "label": text})
                            print(f"      Found {len(districts)} districts")
                        except Exception as e:
                            print(f"      [!] Error getting districts: {e}")
                            districts = []

                        roll_data = {"districts": {}}

                        for district in districts:
                            print(f"      Selecting district: {district['label']}")
                            page.select_option("#district", value=district['value'])
                            page.wait_for_load_state("networkidle")
                            time.sleep(1)  # Wait for AJAX to load constituencies

                            # Get Constituencies
                            try:
                                page.wait_for_selector("#constituency", state="visible", timeout=10000)
                                const_select = page.locator("#constituency")
                                const_options = const_select.locator("option").all()
                                constituencies = []
                                for opt in const_options:
                                    val = opt.get_attribute("value")
                                    text = opt.inner_text().strip()
                                    if val and val != "":
                                        constituencies.append({"value": val, "label": text})
                                print(f"        Found {len(constituencies)} constituencies")
                            except Exception as e:
                                print(f"        [!] Error getting constituencies: {e}")
                                constituencies = []

                            # Get Languages - need to select a constituency first!
                            languages = []
                            if constituencies:
                                # Select first constituency to trigger language load
                                first_const = constituencies[0]
                                print(f"        Selecting constituency for language: {first_const['label']}")
                                page.select_option("#constituency", value=first_const['value'])
                                page.wait_for_load_state("networkidle")
                                time.sleep(1)

                                try:
                                    page.wait_for_selector("#langCd", state="visible", timeout=10000)
                                    lang_select = page.locator("#langCd")
                                    lang_options = lang_select.locator("option").all()
                                    for opt in lang_options:
                                        val = opt.get_attribute("value")
                                        text = opt.inner_text().strip()
                                        if val and val != "":
                                            languages.append({"value": val, "label": text})
                                    print(f"        Found {len(languages)} languages: {[l['label'] for l in languages]}")
                                except Exception as e:
                                    print(f"        [!] Error getting languages: {e}")
                                    languages = [{"value": "ENG", "label": "ENGLISH"}, {"value": "HIN", "label": "HINDI"}]
                            else:
                                languages = [{"value": "ENG", "label": "ENGLISH"}, {"value": "HIN", "label": "HINDI"}]

                            roll_data["districts"][district['label']] = {
                                "constituencies": constituencies,
                                "languages": languages
                            }

                        year_data["roll_types"][roll_type['label']] = roll_data

                    state_data["years"][year['label']] = year_data

                all_data[state['label']] = state_data

            browser.close()

            with open("discovered_structure.json", "w", encoding="utf-8") as f:
                json.dump(all_data, f, indent=2, ensure_ascii=False)

            print("[+] Discovery complete. Structure saved to discovered_structure.json")
            return all_data

    def get_all_parts_from_table(self, page):
        """Get all parts (PDFs) from the table, handling pagination."""
        all_parts = []

        # Wait for table to appear
        try:
            page.wait_for_selector("table.datatable.contenttable-eroll", timeout=10000)
        except:
            print("    [!] Table not found")
            return []

        # First, check if there's pagination
        pagination_container = page.locator(".pagination-outer").first
        if pagination_container.count() > 0:
            # Check if we can navigate - try clicking >> to go to last page
            last_page_btn = page.locator(".control-btn:has-text('>>')").first
            if last_page_btn.count() > 0 and last_page_btn.is_enabled():
                print("    [*] Navigating to last page...")
                last_page_btn.click()
                page.wait_for_load_state("networkidle")
                time.sleep(2)

            # Now iterate backwards through pages
            page_num = 1
            while True:
                # Extract parts from current page
                parts_on_page = self._extract_parts_from_current_page(page)
                print(f"    [*] Page {page_num}: found {len(parts_on_page)} parts")
                all_parts.extend(parts_on_page)

                # Try to go to previous page
                # The buttons are: << (first), < (prev), > (next), >> (last)
                # We need the "<" button (previous)
                prev_btn = page.locator(".control-btn:has-text('<')").first
                # But there might be two: "<<" and "<" - we want the one with just "<"
                # Let's check all control-btn elements
                control_btns = page.locator(".control-btn").all()
                prev_found = False
                for btn in control_btns:
                    text = btn.inner_text().strip()
                    if text == "<" and btn.is_enabled():
                        prev_found = True
                        print(f"    [*] Going to previous page...")
                        btn.click()
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)
                        page_num += 1
                        break

                if not prev_found:
                    # Check if we're on page 1
                    current_page_indicator = page.locator(".control-btn2 strong").first
                    if current_page_indicator.count() > 0:
                        current_page = current_page_indicator.inner_text().strip()
                        if current_page == "1":
                            print(f"    [*] Reached page 1, stopping pagination")
                    break
        else:
            # No pagination, just extract from current page
            all_parts = self._extract_parts_from_current_page(page)

        return all_parts

    def _extract_parts_from_current_page(self, page):
        """Extract part checkboxes and names from current table page."""
        parts = []
        table = page.locator("table.datatable.contenttable-eroll").first
        if table.count() > 0:
            rows = table.locator("tbody tr").all()
            for row in rows:
                checkbox = row.locator("td input[type='checkbox']").first
                part_name_cell = row.locator("td").nth(1)

                if checkbox.count() > 0 and part_name_cell.count() > 0:
                    part_name = part_name_cell.inner_text().strip()
                    # Get the checkbox value or use index
                    parts.append({
                        "name": part_name,
                        "checkbox": checkbox
                    })
        return parts

    def download_all_parts_for_combination(self, page, params, state_label, year_label, roll_label, dist_label, const_label, lang_label):
        """Download all parts (PDFs) for a given combination by iterating through pagination."""

        try:
            # Select all dropdowns using values for reliability
            page.select_option("#stateCode", value=params['state'])
            page.wait_for_load_state("networkidle")
            time.sleep(1.5)

            page.select_option("#revyear", value=params['year'])
            page.wait_for_load_state("networkidle")
            time.sleep(1)

            # Check for alert after year selection
            alerts = page.locator(".library-alert, .alert").all()
            for alert in alerts:
                alert_text = alert.inner_text()
                if "not available" in alert_text.lower() or "warning" in alert_text.lower():
                    return False, f"Alert: {alert_text}"

            # Use value for rollType - need to find it
            roll_select = page.locator("#roleType")
            roll_options = roll_select.locator("option").all()
            roll_value = None
            for opt in roll_options:
                if opt.inner_text().strip() == params['rollType']:
                    roll_value = opt.get_attribute("value")
                    break

            if roll_value:
                page.select_option("#roleType", value=roll_value)
            else:
                return False, f"Roll type not found: {params['rollType']}"

            page.wait_for_load_state("networkidle")
            time.sleep(1)

            # District
            dist_select = page.locator("#district")
            dist_options = dist_select.locator("option").all()
            dist_value = None
            for opt in dist_options:
                if opt.inner_text().strip() == params['district']:
                    dist_value = opt.get_attribute("value")
                    break

            if dist_value:
                page.select_option("#district", value=dist_value)
            else:
                return False, f"District not found: {params['district']}"

            page.wait_for_load_state("networkidle")
            time.sleep(1)

            # Constituency
            const_select = page.locator("#constituency")
            const_options = const_select.locator("option").all()
            const_value = None
            for opt in const_options:
                if opt.inner_text().strip() == params['constituency']:
                    const_value = opt.get_attribute("value")
                    break

            if const_value:
                page.select_option("#constituency", value=const_value)
            else:
                return False, f"Constituency not found: {params['constituency']}"

            time.sleep(1)

            # Language - wait for options to load (wait for any option with a value)
            page.wait_for_selector("#langCd option[value]", state="attached", timeout=10000)
            lang_select = page.locator("#langCd")
            lang_options = lang_select.locator("option").all()
            lang_value = None
            for opt in lang_options:
                if opt.inner_text().strip() == params['language']:
                    lang_value = opt.get_attribute("value")
                    break

            if lang_value:
                page.select_option("#langCd", value=lang_value)
            else:
                return False, f"Language not found: {params['language']}"

            time.sleep(1)

            # Now the table with parts should be visible
            # Get all parts across all pages
            all_parts = self.get_all_parts_from_table(page)

            if not all_parts:
                print(f"      [*] No parts found for this combination")
                return False, "No parts found"

            print(f"      [*] Found {len(all_parts)} parts to download")

            # Select all parts
            for part in all_parts:
                if part["checkbox"].count() > 0:
                    part["checkbox"].check()

            time.sleep(0.5)

            # Handle Captcha
            captcha_img = page.locator("img[alt='captcha'], img[alt='Captcha'], img[id='captchaImg'], img.captcha").first
            if captcha_img.count() == 0:
                captcha_img = page.locator("#captcha").locator("..").locator("img").first

            src = captcha_img.get_attribute("src")
            if src and src.startswith("data:image"):
                # Handle both jpg and png
                if "base64," in src:
                    b64_data = src.split(",")[1]
                    with open(CAPTCHA_PATH, "wb") as f:
                        f.write(base64.b64decode(b64_data))
            else:
                captcha_img.screenshot(path=CAPTCHA_PATH)

            # Solve captcha
            captcha_code = self.solve_captcha_with_vision(CAPTCHA_PATH)
            if captcha_code == "MANUAL":
                return False, "Captcha requires manual solving"

            # Submit and Download
            with page.expect_download(timeout=60000) as download_info:
                page.fill("#captcha", captcha_code)
                page.click("button.btn.btn-block.submit")

            download = download_info.value
            filename = download.suggested_filename()

            # Create organized folder structure
            safe_state = state_label.replace(" ", "_").replace("&", "and").replace("/", "_")
            safe_year = year_label.replace(" ", "_")
            safe_roll = roll_label.replace(" ", "_").replace("-", "_").replace("/", "_")
            safe_dist = dist_label.replace(" ", "_").replace("/", "_")
            safe_const = const_label.replace(" ", "_").replace("-", "_").replace("/", "_")
            safe_lang = lang_label.replace(" ", "_")

            folder_path = Path(OUTPUT_FOLDER) / safe_state / safe_year / safe_roll / safe_dist / safe_const / safe_lang
            folder_path.mkdir(parents=True, exist_ok=True)

            save_path = folder_path / filename
            download.save_as(str(save_path))

            self.downloaded_files.append({
                "path": str(save_path),
                "relative": str(save_path.relative_to(OUTPUT_FOLDER)),
                "state": state_label,
                "year": year_label,
                "roll_type": roll_label,
                "district": dist_label,
                "constituency": const_label,
                "language": lang_label,
                "parts_count": len(all_parts),
                "parts": [p["name"] for p in all_parts]
            })

            print(f"[+] Downloaded: {save_path} (contains {len(all_parts)} parts)")
            return True, str(save_path)

        except Exception as e:
            return False, str(e)

    def download_all(self, structure, max_per_category=None, target_state=None, target_year=None):
        """Download all PDFs based on discovered structure."""
        print("[*] Starting comprehensive download...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")

            total = 0
            successful = 0
            failed = 0

            # Pre-fetch state values
            state_values = {}
            browser2 = p.chromium.launch(headless=True)
            page2 = browser2.new_page()
            page2.goto(BASE_URL)
            page2.wait_for_load_state("networkidle")
            opts = page2.locator("#stateCode option").all()
            for opt in opts:
                val = opt.get_attribute("value")
                text = opt.inner_text().strip()
                if val and val != "":
                    state_values[text] = val
            browser2.close()

            for state_label, state_data in structure.items():
                # Filter by target state if specified
                if target_state and target_state.lower() not in state_label.lower():
                    continue

                # Find state value
                state_value = state_values.get(state_label)
                if not state_value:
                    print(f"[!] Could not find value for state: {state_label}")
                    continue

                print(f"\n{'='*60}")
                print(f"Processing STATE: {state_label}")
                print(f"{'='*60}")

                for year_label, year_data in state_data.get("years", {}).items():
                    if target_year and target_year not in year_label:
                        continue

                    print(f"\n  YEAR: {year_label}")

                    for roll_label, roll_data in year_data.get("roll_types", {}).items():
                        print(f"    ROLL TYPE: {roll_label}")

                        dist_count = 0
                        for dist_label, dist_data in roll_data.get("districts", {}).items():
                            if max_per_category and dist_count >= max_per_category:
                                break
                            dist_count += 1

                            const_count = 0
                            for const in dist_data.get("constituencies", []):
                                if max_per_category and const_count >= max_per_category:
                                    break
                                const_count += 1

                                for lang in dist_data.get("languages", []):
                                    total += 1
                                    params = {
                                        "state": state_value,
                                        "year": year_label,  # year value is the same as label (e.g., "2025")
                                        "rollType": roll_label,
                                        "district": dist_label,
                                        "constituency": const["label"],
                                        "language": lang["label"]
                                    }

                                    print(f"      [{total}] {dist_label} | {const['label']} | {lang['label']}")
                                    success, result = self.download_all_parts_for_combination(
                                        page, params, state_label, year_label, roll_label,
                                        dist_label, const["label"], lang["label"]
                                    )

                                    if success:
                                        successful += 1
                                    else:
                                        failed += 1
                                        print(f"        [!] Failed: {result}")

                                    # Small delay between requests
                                    time.sleep(3)

            browser.close()

            print(f"\n{'='*60}")
            print(f"DOWNLOAD COMPLETE")
            print(f"Total attempted: {total}")
            print(f"Successful: {successful}")
            print(f"Failed: {failed}")
            print(f"{'='*60}")

            self.create_organized_zips()

    def create_organized_zips(self):
        """Create organized ZIP files based on folder structure."""
        print("[*] Creating organized ZIP archives...")

        # Create ZIP per state
        state_folders = [f for f in os.listdir(OUTPUT_FOLDER) if os.path.isdir(os.path.join(OUTPUT_FOLDER, f))]

        for state_folder in state_folders:
            state_path = os.path.join(OUTPUT_FOLDER, state_folder)
            zip_name = f"electoral_rolls_{state_folder}.zip"

            print(f"  Creating {zip_name}...")
            with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(state_path):
                    for file in files:
                        if file.endswith(".pdf") or file.endswith(".zip"):
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, OUTPUT_FOLDER)
                            zipf.write(full_path, arcname)

            print(f"  [+] Created {zip_name}")

        # Also create a master ZIP with everything
        master_zip = "electoral_rolls_ALL.zip"
        print(f"  Creating master archive {master_zip}...")
        with zipfile.ZipFile(master_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(OUTPUT_FOLDER):
                for file in files:
                    if file.endswith(".pdf") or file.endswith(".zip"):
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, OUTPUT_FOLDER)
                        zipf.write(full_path, arcname)

        print(f"[+] All ZIP archives created!")

        # Save download log
        with open("download_log.json", "w", encoding="utf-8") as f:
            json.dump(self.downloaded_files, f, indent=2, ensure_ascii=False)
        print("[+] Download log saved to download_log.json")

def upload_to_minio(self):
        """Upload downloaded files and ZIPs to MinIO."""
        try:
            from minio_client import MinIOClient
            client = MinIOClient()
            if not client.is_configured():
                print("[!] MinIO not configured. Set MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY in .env")
                return False

            # Find generated ZIP files
            zip_files = []
            for f in os.listdir("."):
                if f.startswith("electoral_rolls_") and f.endswith(".zip"):
                    zip_files.append(Path(f))

            if not zip_files:
                print("[!] No ZIP files found to upload. Run download first.")
                return False

            print(f"[*] Uploading to MinIO: {len(zip_files)} ZIP files + PDFs...")
            results = client.upload_all_organized(
                output_folder=Path("downloaded_pdfs"),
                zip_files=zip_files
            )

            print(f"[+] MinIO upload complete:")
            print(f"    PDFs: {results['pdfs']['uploaded']} uploaded, {results['pdfs']['failed']} failed")
            print(f"    ZIPs: {results['zips']['uploaded']} uploaded, {results['zips']['failed']} failed")
            print(f"    Log: {'uploaded' if results['log'] else 'failed/not found'}")
            return True

        except ImportError:
            print("[!] MinIO client not available. Install minio: pip install minio")
            return False
        except Exception as e:
            print(f"[!] MinIO upload error: {e}")
            return False

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ECI Electoral Roll Downloader")
    parser.add_argument("--discover", action="store_true", help="Only discover structure, don't download")
    parser.add_argument("--download", action="store_true", help="Download all (requires discovered_structure.json)")
    parser.add_argument("--max-per-category", type=int, default=None, help="Limit items per category for testing")
    parser.add_argument("--vision-key", type=str, default=None, help="Vision API key for captcha solving")
    parser.add_argument("--state", type=str, default=None, help="Specific state to download (e.g., 'NCT OF Delhi')")
    parser.add_argument("--year", type=str, default=None, help="Specific year to download (e.g., '2025')")
    parser.add_argument("--upload-to-minio", action="store_true", help="Upload downloaded files to MinIO after download")

    args = parser.parse_args()

    downloader = ECIDownloader(vision_api_key=args.vision_key)

    if args.discover:
        structure = downloader.discover_all_options()
    elif args.download:
        if os.path.exists("discovered_structure.json"):
            with open("discovered_structure.json", "r", encoding="utf-8") as f:
                structure = json.load(f)
        else:
            print("[*] No discovered structure found, discovering first...")
            structure = downloader.discover_all_options()

        downloader.download_all(structure, max_per_category=args.max_per_category,
                               target_state=args.state, target_year=args.year)

        # Upload to MinIO if requested
        if args.upload_to_minio:
            downloader.upload_to_minio()
    else:
        # Default: discover then download with limit for testing
        structure = downloader.discover_all_options()
        downloader.download_all(structure, max_per_category=1)  # Test with 1 per category