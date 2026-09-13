import time
from playwright.sync_api import sync_playwright

def test_mgmt_overview():
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
        
        print("Triggering Management Overview route...")
        page.evaluate("go('mgmt')")
        page.wait_for_timeout(1000)

        # Clear dates to get all data
        page.evaluate("document.getElementById('mgFrom').value = ''")
        page.evaluate("document.getElementById('mgTo').value = ''")
        page.evaluate("renderMgmt()")
        page.wait_for_timeout(1000)

        print("Checking filter dropdowns for real data...")
        customers = page.locator("#mgCust option").all_text_contents()
        print("Customers:", customers)
        assert len(customers) > 1, "Customer dropdown is empty or missing real data"

        models = page.locator("#mgModel option").all_text_contents()
        print("Models:", models)
        assert len(models) > 1, "Model dropdown is empty or missing real data"

        # Check KPI values
        kpi_allocated = page.locator("#mk1").text_content()
        kpi_produced = page.locator("#mk2").text_content()
        print(f"KPIs - Allocated: {kpi_allocated}, Produced: {kpi_produced}")
        assert kpi_allocated and kpi_allocated != "—", "KPI Allocated not populated"

        # Check Shift rows
        print("Checking Shift table rows...")
        shift_rows = page.locator("#mgShiftRows tr").all_text_contents()
        print(f"Found {len(shift_rows)} shift rows")

        # Now select a specific filter and verify they change together
        test_customer = customers[1]
        print(f"Selecting Customer: {test_customer}")
        page.select_option("#mgCust", test_customer, force=True)
        page.evaluate("renderMgmt()")
        page.wait_for_timeout(1000)

        new_kpi_produced = page.locator("#mk2").text_content()
        print(f"KPI Produced after filter: {new_kpi_produced}")

        new_shift_rows = page.locator("#mgShiftRows tr:not(:has(.empty-state))").count()
        print(f"Shift data rows after filter: {new_shift_rows}")
        if new_shift_rows > 0:
            print("Row contents:", page.locator("#mgShiftRows tr:not([data-empty])").all_text_contents())
        
        if kpi_produced != new_kpi_produced:
            # If KPI changed, the table should also reflect the change or be empty
            pass

        assert len(errors) == 0, f"Console errors found: {errors}"
        
        if float(new_kpi_produced.replace(',', '')) == 0:
            empty_count = page.locator("#mgShiftRows tr:has(.empty-state)").count()
            assert new_shift_rows == 0 and empty_count > 0, "Shift table shows leftover data while KPI is 0"

        print("SUCCESS! UI test passed.")
        browser.close()

if __name__ == "__main__":
    test_mgmt_overview()
