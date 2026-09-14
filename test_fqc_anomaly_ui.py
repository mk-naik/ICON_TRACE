import time
from playwright.sync_api import sync_playwright

def test_fqc_anomaly():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        errors = []
        page.on("pageerror", lambda err: errors.append(f"JS ERROR: {err}"))
        page.on("console", lambda msg: errors.append(f"CONSOLE: {msg.text}") if msg.type == "error" else None)

        # Mock the API response to force anomalies to be returned
        page.route("**/api/fqc/anomalies*", lambda route: route.fulfill(
            json={
                "available": True,
                "junk": [{"at": "12:00", "id": "JUNK123", "pmax": "500"}],
                "failed": [{"serial": "SER123", "attempts": 2, "at": "12:05", "why": "Bad connection"}],
                "calibration": 0
            }
        ))
        
        print("Navigating to root...")
        page.goto("http://127.0.0.1:8090/")
        page.wait_for_load_state("networkidle")
        
        print("Signing in...")
        page.evaluate("signIn()")
        page.wait_for_timeout(500)
        
        print("Triggering FQC Dashboard route...")
        page.evaluate("go('dash')")
        page.wait_for_timeout(1000)

        # Check if the anomalies button is present in the table
        print("Clicking Anomaly view button...")
        try:
            # We look for the button that calls renderAnomalies()
            page.evaluate("renderAnomalies()")
            page.wait_for_selector("#fqcAnomaliesModal", timeout=3000)
        except Exception as e:
            print(f"Exception waiting for modal: {e}")
            if errors:
                print(f"Console errors: {errors}")
        
        modal_count = page.locator("#fqcAnomaliesModal").count()
        assert modal_count == 1, f"Anomaly modal was not rendered. Errors: {errors}"

        header_text = page.locator("#fqcAnomaliesModal h3").text_content()
        assert "Tester Anomalies" in header_text

        print("Anomaly modal successfully found in the DOM!")
        print("SUCCESS! UI test passed.")
        browser.close()

if __name__ == "__main__":
    test_fqc_anomaly()
