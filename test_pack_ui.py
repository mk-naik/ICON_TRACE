import time
from playwright.sync_api import sync_playwright

def test_pack_dashboard():
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
        
        print("Triggering Packing Log route...")
        page.evaluate("go('packdash')")
        page.wait_for_timeout(1000)

        print("Checking filter dropdowns for real data...")
        customers = page.locator("#pkCust option").all_text_contents()
        print("Customers:", customers)
        assert len(customers) > 1, "Customer dropdown is empty or missing real data"

        models = page.locator("#pkModel option").all_text_contents()
        print("Models:", models)
        assert len(models) > 1, "Model dropdown is empty or missing real data"

        # Check KPI values
        kpi_lists_created = page.locator("#v-packdash .grid.g4 .kpi").nth(0).locator(".v").text_content()
        print(f"KPIs - Packing lists created: {kpi_lists_created}")
        assert kpi_lists_created and kpi_lists_created != "—", "KPI Packing lists created not populated"

        print("Checking Packing log table rows...")
        rows = page.locator("#pkBoxRows tr").count()
        print(f"Found {rows} box rows")

        # Now select a specific filter and verify they change together
        test_customer = customers[1]
        print(f"Selecting Customer: {test_customer}")
        page.select_option("#pkCust", test_customer, force=True)
        page.wait_for_timeout(1000)

        new_kpi = page.locator("#v-packdash .grid.g4 .kpi").nth(0).locator(".v").text_content()
        print(f"KPI Packing lists after filter: {new_kpi}")

        new_rows = page.locator("#pkBoxRows tr:not(:has(.empty-state))").count()
        print(f"Packing log rows after filter: {new_rows}")

        assert len(errors) == 0, f"Console errors found: {errors}"
        
        # Verify it doesn't show leftovers. If there's 0 KPI, shift rows should be 0.
        if float(new_kpi.replace(',', '')) == 0:
            empty_count = page.locator("#pkBoxRows tr:has(.empty-state)").count()
            assert new_rows == 0 and empty_count > 0, "Packing table shows leftover data while KPI is 0"

        print("SUCCESS! UI test passed.")
        browser.close()

if __name__ == "__main__":
    test_pack_dashboard()
