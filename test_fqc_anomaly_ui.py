import time
from playwright.sync_api import sync_playwright

def test_fqc_anomaly():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        errors = []
        page.on("pageerror", lambda err: errors.append(f"JS ERROR: {err}"))
        page.on("console", lambda msg: errors.append(f"CONSOLE: {msg.text}") if msg.type == "error" else None)
        
        print("Navigating to root...")
        page.goto("http://127.0.0.1:8090/")
        page.wait_for_load_state("networkidle")
        
        print("Signing in...")
        page.evaluate("signIn()")
        page.wait_for_timeout(500)
        
        print("Triggering FQC route...")
        page.evaluate("go('fqc')")
        page.wait_for_timeout(1000)

        # Check if the anomalies card exists
        print("Checking if anomalies card is present...")
        if errors:
            print(f"Errors before wait: {errors}")
        try:
            page.wait_for_selector("#fqcAnomaliesCard", timeout=3000)
        except Exception as e:
            print(f"Exception waiting for card: {e}")
            if errors:
                print(f"Console errors: {errors}")
        
        card_count = page.locator("#fqcAnomaliesCard").count()
        assert card_count == 1, f"Anomaly card was not rendered. Errors: {errors}"

        header_text = page.locator("#fqcAnomaliesCard h3").text_content()
        assert "What the tester wrote that no lookup will find" in header_text

        print("Anomaly card successfully found in the DOM!")
        print("SUCCESS! UI test passed.")
        browser.close()

if __name__ == "__main__":
    test_fqc_anomaly()
