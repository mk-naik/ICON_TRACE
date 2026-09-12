from playwright.sync_api import sync_playwright

def test_fqc_recent():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: print(f"CONSOLE: {msg.text}"))
        page.goto("http://127.0.0.1:5000/")
        page.wait_for_load_state("networkidle")
        
        print("Signing in...")
        page.evaluate("signIn()")
        page.wait_for_timeout(500)

        print("Triggering FQC Entry route...")
        page.evaluate("go('fqc')")
        page.wait_for_timeout(1000)

        print("Checking for filters in Recent Gradings...")
        filters = page.locator("#v-fqc .filters").count()
        print(f"Filters found: {filters}")
        
        # Check if the existing data-role="filter" elements are present
        data_filters = page.locator("#v-fqc [data-role='filter']").count()
        print(f"Data-role filters found: {data_filters}")

        browser.close()

if __name__ == "__main__":
    test_fqc_recent()
