import time
from playwright.sync_api import sync_playwright

def test_fqc_dashboard():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Navigating to root...")
        page.on("pageerror", lambda err: print(f"JS ERROR: {err}"))
        page.on("console", lambda msg: print(f"CONSOLE: {msg.text}"))
        page.goto("http://127.0.0.1:5000/")
        page.wait_for_load_state("networkidle")
        
        # Must sign in to initialize the live layer hooks!
        print("Signing in...")
        page.evaluate("signIn()")
        page.wait_for_timeout(500)

        print("Triggering dashboard route...")
        page.evaluate("go('dash')")
        page.wait_for_timeout(1000)

        # Clear date filters to ensure we get data from the DB
        print("Clearing date filters...")
        page.evaluate("document.getElementById('fFrom').value = ''")
        page.evaluate("document.getElementById('fTo').value = ''")
        page.evaluate("fqcApply()")
        page.wait_for_timeout(1000)

        # Step 1: Check shift dropdown has options
        shifts = page.locator("#fDashShift option").all_text_contents()
        assert len(shifts) > 1, "Shift dropdown should have options"
        print("Shift dropdown options found:", shifts)

        # Step 2: Select 'A' and wait for DOM update
        print("Selecting Shift A...")
        page.select_option("#fDashShift", "A", force=True)
        page.wait_for_timeout(1000) # Give it time to fetch and render

        # Step 3: Check Customer dropdown populated dynamically
        customers = page.locator("#fDashCust option").all_text_contents()
        assert len(customers) > 1, "Customer dropdown should be dynamically populated"
        print("Dynamic customer options found:", customers)

        # Step 4: Select a Customer to test cascading filter and no blank results
        if len(customers) > 1:
            test_customer = customers[1]
            print(f"Selecting Customer: {test_customer}")
            page.select_option("#fDashCust", test_customer, force=True)
            page.wait_for_timeout(1000)

            # Check if grid updated without going blank
            rows = page.locator("#shiftRows tr:not([data-empty])").count()
            print(f"Rows found after cascading filter: {rows}")
            assert rows > 0, "Dashboard went blank after selecting customer!"

        # Step 5: Test 'View' button in shift table
        if page.locator("#shiftRows button").count() > 0:
            print("Clicking View action...")
            page.evaluate("document.querySelector('#shiftRows button').click()")
            page.wait_for_selector("#mdl", state="visible")
            page.wait_for_timeout(1000)
            
            # Step 6: Verify modal is not blank
            mdl_rows = page.locator("#mdlRows tr:not([data-empty])").count()
            print(f"Modal rows found: {mdl_rows}")
            empty_state = page.locator("#mdlRows .empty-state").count()
            assert empty_state == 0, "Modal showed 'No modules match these filters' (Blank View bug!)"
            assert mdl_rows > 0, "Modal is empty!"

        print("SUCCESS! All UI behaviors passed flawlessly.")
        browser.close()

if __name__ == "__main__":
    test_fqc_dashboard()
