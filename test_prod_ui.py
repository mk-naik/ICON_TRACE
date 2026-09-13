import time
from playwright.sync_api import sync_playwright

def test_prod_dashboard():
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
        
        print("Triggering Production Dashboard route...")
        page.evaluate("go('proddash')")
        page.wait_for_timeout(1000)

        print("Checking filter dropdowns for real data...")
        customers = page.locator("#pdCust option").all_text_contents()
        print("Customers:", customers)
        assert len(customers) > 1, "Customer dropdown is empty or missing real data"

        models = page.locator("#pdModel option").all_text_contents()
        print("Models:", models)
        assert len(models) > 1, "Model dropdown is empty or missing real data"

        # Check KPI values
        kpi_allocated = page.locator("#pk1").text_content()
        kpi_produced = page.locator("#pk2").text_content()
        print(f"KPIs - Allocated: {kpi_allocated}, Produced: {kpi_produced}")
        assert kpi_allocated and kpi_allocated != "—", "KPI Allocated not populated"

        print("Checking Line & shift performance rows...")
        shift_rows = page.locator("#pdLineRows tr").count()
        print(f"Found {shift_rows} shift rows")

        # Now select a specific filter and verify they change together
        test_customer = customers[1]
        print(f"Selecting Customer: {test_customer}")
        page.select_option("#pdCust", test_customer, force=True)
        page.wait_for_timeout(1000)

        new_kpi_produced = page.locator("#pk2").text_content()
        print(f"KPI Produced after filter: {new_kpi_produced}")

        new_shift_rows = page.locator("#pdLineRows tr:not(:has(.empty-state))").count()
        print(f"Shift data rows after filter: {new_shift_rows}")

        assert len(errors) == 0, f"Console errors found: {errors}"
        
        # Verify it doesn't show leftovers. If there's 0 KPI, shift rows should be 0.
        if float(new_kpi_produced.replace(',', '')) == 0:
            empty_count = page.locator("#pdLineRows tr:has(.empty-state)").count()
            assert new_shift_rows == 0 and empty_count > 0, "Shift table shows leftover data while KPI is 0"

        print("SUCCESS! UI test passed.")
        browser.close()

if __name__ == "__main__":
    test_prod_dashboard()
