def test_lockout_escalation_ui(lab_env):

    import time, subprocess, sys, os
    from playwright.sync_api import sync_playwright
    
    # Create sa1 and op1 so they actually exist in the DB!
    env = lab_env[3]
    cli_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon_auth_cli.py")
    subprocess.run([sys.executable, cli_path, "create-superadmin", "sa1", "SA One"], env=env, check=True)
    
    import sqlite3, store, icon_auth
    old = store.DB_PATH
    store.DB_PATH = lab_env[0]
    with store.conn() as (cx, cur):
        icon_auth.create_operator(cur, "sa1", "op1", "Op One", "FQC", "TempPass123!")
        # Also create op2 for later reset test
        icon_auth.create_operator(cur, "sa1", "op2", "Op Two", "FQC", "TempPass123!")
    store.DB_PATH = old
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        # Run it as an operator first
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")

        # 1 fail
        page.fill("input[name='login_id']", "op1")
        page.fill("input[name='credential']", "wrong1")
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.click("button[type='submit']")
        assert "1 failed attempt" in page.locator(".error").inner_text()

        # check countdown
        page.wait_for_selector("text=Wait", timeout=2000)
        time.sleep(2)
        assert page.locator("button[type='submit']").inner_text() == "Sign In"

        # 2 fails
        page.fill("input[name='login_id']", "op1")
        page.fill("input[name='credential']", "wrong2")
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.click("button[type='submit']")
        page.wait_for_selector("text=2 failed attempts", timeout=2000)
        page.wait_for_selector("text=Wait", timeout=2000)
        time.sleep(4)

        # 3 fails
        page.fill("input[name='login_id']", "op1")
        page.fill("input[name='credential']", "wrong3")
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.click("button[type='submit']")
        page.wait_for_selector("text=3 failed attempts", timeout=2000)

        # Countdown survives page refresh
        page.reload()
        page.wait_for_selector("text=Wait", timeout=2000)
        time.sleep(8)

        # Now test as sa1
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        page.evaluate("sessionStorage.clear()")

        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", "wrong1")
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.click("button[type='submit']")
        assert "1 failed attempt" in page.locator(".error").inner_text()

        # successful sign-in resets counter
        time.sleep(2)
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        
        # log in with op2 which is fresh and not locked out
        page.fill("input[name='login_id']", "op2")
        page.fill("input[name='credential']", "TempPass123!") 
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.click("button[type='submit']")
        
        # Should redirect to change password
        page.wait_for_selector("text=Change Password", timeout=2000)

        # Now verify counter is reset by checking sessionStorage
        fails = page.evaluate("sessionStorage.getItem('fails')")
        assert fails is None

        # logout and try again - counter should be reset
        page.goto("http://127.0.0.1:8091/logout")
        page.goto("http://127.0.0.1:8091/")
        
        page.fill("input[name='login_id']", "sa1")
        page.fill("input[name='credential']", "wrong1")
        page.evaluate("sessionStorage.setItem('submitted', '1')")
        page.click("button[type='submit']")
        assert "1 failed attempt" in page.locator(".error").inner_text()
