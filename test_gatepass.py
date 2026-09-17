import unittest
import json
import db
import store
import datetime
from app import app

class TestGatepass(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        import os
        try:
            os.remove("icontrace.db")
        except:
            pass
        with store.conn() as (cx, cur):
            
            
            
            
            
            
            
            
            
            # Setup a challan and boxes
            ch_id = store.insert(cur, "challan", {
                "fy": 2026,
                "seq": 1,
                "challan_date": "2026-09-17",
                "buyer_name": "Test Party",
                "qty": 72,
                "created_by": "Test User"
            })
            self.ch_id = ch_id
            
            box1_id = store.insert(cur, "box", {
                "seq": 1, "pack_date": "2026-09-17",
                "capacity": 36,
                "qty": 36,
                "model": "ISEN625",
                "grade": "A",
                "created_by": "Test"
            })
            box2_id = store.insert(cur, "box", {
                "seq": 2, "pack_date": "2026-09-17",
                "capacity": 36,
                "qty": 36,
                "model": "ISEN625",
                "grade": "A",
                "created_by": "Test"
            })
            
            store.insert(cur, "challan_box", {
                "challan_id": ch_id,
                "box_no": "TESTB1", "qty": 36,
                "loading_status": "loaded", "load_order": 1, "pack_date": "2026-09-17"
            })
            store.insert(cur, "challan_box", {
                "challan_id": ch_id,
                "box_no": "TESTB2", "qty": 36,
                "loading_status": "pending", "load_order": 2, "pack_date": "2026-09-17"
            })

    def test_module_mode_refusal(self):
        # A module mode gatepass against an incomplete challan must be refused
        resp = self.app.post("/api/gatepass", data=json.dumps({
            "is_solar": True,
            "challan_id": self.ch_id
        }))
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data)
        self.assertFalse(data["ok"])
        self.assertTrue("Loading verification is not complete" in data["why"])

    def test_module_mode_success(self):
        # Set all to loaded
        with store.conn() as (cx, cur):
            cur.execute("UPDATE challan_box SET loading_status='loaded' WHERE challan_id=%s", (self.ch_id,))
            
        resp = self.app.post("/api/gatepass", data=json.dumps({
            "is_solar": True,
            "challan_id": self.ch_id,
            "kind": "NRGP",
            "party": "Test Party",
            "description": "Modules"
        }))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["ok"])
        self.assertIn("gatepass_id", data)

    def test_standalone_mode(self):
        # Even if challan is incomplete, standalone mode without challan should pass
        resp = self.app.post("/api/gatepass", data=json.dumps({
            "is_solar": False,
            "kind": "RGP",
            "party": "Standalone",
            "description": "Tools"
        }))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["ok"])

if __name__ == "__main__":
    unittest.main()
