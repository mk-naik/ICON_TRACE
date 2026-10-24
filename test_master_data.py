"""
ICON TRACE - the customer and model masters are tables, kept in Admin.

    python test_master_data.py

THE RULES THIS FILE DEFENDS (DECISIONS 13, 24 Oct 2026)

    Customers and models were Python lists, so adding one meant editing source
    and redeploying. They are the `customer` and `model` tables now - seeded
    once from those lists, and a redeploy never brings back a removed row or
    undoes an edit. A Super Admin keeps them; an Admin reads them.

  1. A code is never edited - every indent, pallet, serial and line stores it.
     A model's family is fixed too (it is the middle of its item codes), and a
     code shaped ISEN<watts>-<family> must agree with its wattage and family.
  2. Removal stamps the row: reason mandatory, what still names it said first,
     audited. The row stays, a record that named it still names it, and a
     removed row is not edited (409, naming who removed it and when). Restore
     takes the stamp off - Super Admin, reason mandatory.
  3. Icon Stock is never removed: it is the "unallocated" value, not a customer.
  4. A model whose serials exist may be removed (Mukesh, 24 Oct): its use-check
     leads with what is still to plan on it; nothing new is planned on it until
     it is restored, while its modules are packed as before.
  5. A packing list prints the master's CURRENT name; a challan keeps the
     invoice's text it was made with (Mukesh, 24 Oct). A rename keeps the old
     name as one of the customer's names, so the rows Planning wrote under it
     still find it - in a filter, on screen and in Search & Trace.
  6. Every create, edit, removal and restore is an entity_revision row with the
     row before and after, and an audit row.
"""

import json, re, sys, traceback

import test_challan as T            # sets the throwaway database; runs nothing
import test_challan_print as TP     # noqa: E402
import store                        # noqa: E402
import db                           # noqa: E402
import icon_customers as customers  # noqa: E402
import icon_models as models        # noqa: E402
import auth_test_helper as AUTH     # noqa: E402

APP = T.APP
_results = []


def test(name):
    def deco(fn):
        _results.append((name, fn))
        return fn
    return deco


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_data(as_text=True)[:500])
    return r.get_json()


def refused(r, code, *words):
    d = r.get_json(silent=True) or {}
    assert r.status_code == code and d.get("ok") is False, (r.status_code, d)
    for w in words:
        assert w in d["why"], (w, d["why"])
    return d["why"]


def revisions(kind, key):
    with store.conn() as (cx, cur):
        return list(reversed(db.entity_revisions(cur, kind, key)))


def audits(action):
    with store.conn() as (cx, cur):
        return store.rows(cur, "SELECT * FROM dispatch_audit WHERE action=%s ORDER BY audit_id",
                          (action,))


def custom_indent(c, no, customer, model, qty=10):
    """A custom-serial indent - its serials are tokens, so Planning can allocate
    them through the real route without an ICON range. Returns its line id."""
    item = next(i["item_code"] for i in models.ITEMS
                if i["model"] == model and i["cell_type"] == "DCR")
    r = c.post("/api/indent", json={"indent_no": no, "indent_date": "2026-10-01",
               "customer": customer, "build_type": "make_to_order", "custom_serial": True,
               "items": [{"item_code": item, "qty": qty}]}).get_json()
    assert r.get("ok"), r
    with store.conn() as (cx, cur):
        return store.one(cur, "SELECT l.indent_line_id AS id FROM indent_line l JOIN indent i "
                              "ON i.indent_id=l.indent_id WHERE i.indent_no=%s", (no,))["id"]


def allocate(c, line_id, serials, **extra):
    body = {"indent_line_id": line_id, "qty": len(serials), "serials": serials,
            "materials": [], "alloc_type": "post_shared"}
    body.update(extra)
    return c.post("/api/allocation", json=body)


GOOD_GSTIN = "22AAACB1234C1Z" + customers.gstin_check_letter("22AAACB1234C1Z")


# --------------------------------------------------------------------------

@test("the tables are seeded from the old lists: 75 customers, 10 models, the same item "
      "codes - and a redeploy (the seed again) brings back no removed row and undoes no edit")
def t_seed_once():
    c = T.setup()
    d = ok(c.get("/api/admin/customers"))
    assert len(d["customers"]) == 75 and not d["removed"], len(d["customers"])
    assert d["next_code"] == "C0078", d["next_code"]
    m = ok(c.get("/api/admin/models"))
    assert len(m["models"]) == 10 and not m["removed"]
    assert models.get_item("ISEN600-G12R-DCR")["item_code"] == "F02010001"
    assert models.get_item("ISEN600-G2X-NDCR")["item_code"] == "F02020004"
    ok(c.put("/api/customer/C0001", json={"name": "Agni Green Power Limited",
                                          "gstins": ["15AACCA2122Q1ZT"],
                                          "aliases": ["AGNI"], "state": "Mizoram"}))
    ok(c.delete("/api/customer/C0009", json={"reason": "a duplicate"}))
    ok(c.delete("/api/model/ISEN605-G12R", json={"reason": "never built"}))
    store._ready = False
    store.ensure()                                   # what a restart / redeploy runs
    with store.conn() as (cx, cur):
        n_c = store.one(cur, "SELECT COUNT(*) AS n FROM customer")["n"]
        n_m = store.one(cur, "SELECT COUNT(*) AS n FROM model")["n"]
    assert (n_c, n_m) == (75, 10), (n_c, n_m)
    assert customers.get("C0001")["name"] == "Agni Green Power Limited"
    assert customers.get("C0001")["aliases"] == ["AGNI"]
    assert customers.get("C0009")["removed_at"], "the seed brought a removed customer back"
    assert models.get("ISEN605-G12R")["removed_at"], "the seed brought a removed model back"


@test("a new customer gets the next code from the server, and is refused for a GSTIN that "
      "fails its check letter, one another customer holds, an alias that names another "
      "customer, no name, or markup")
def t_customer_create():
    c = T.setup()
    refused(c.post("/api/customer", json={"name": "Nova Solar", "gstins": ["22AADCI5761L1Z4"]}),
            400, "fails its check letter", "ends in G")
    refused(c.post("/api/customer", json={"name": "Nova Solar", "gstins": ["15AACCA2122Q1ZT"]}),
            400, "Agni Green Power Limited (Mz)", "C0001")
    refused(c.post("/api/customer", json={"name": "Nova Solar", "aliases": ["BOROSIL"]}),
            400, "already names Borosil")
    refused(c.post("/api/customer", json={"name": "  "}), 400, "needs a name")
    refused(c.post("/api/customer", json={"name": "<b>Nova</b>"}), 400, "without < or >")
    d = ok(c.post("/api/customer", json={"name": "Nova Solar Pvt Ltd", "code": "HACK1",
                                         "gstins": ["%s Raipur plant" % GOOD_GSTIN],
                                         "aliases": ["NOVA", "nova"], "state": "Chhattisgarh"}))
    assert d["code"] == "C0078", d                      # the browser's code is never taken
    assert d["customer"]["gstins"] == [[GOOD_GSTIN, "Raipur plant"]]
    assert d["customer"]["aliases"] == ["NOVA"], "an alias was kept twice"
    assert customers.resolve("NOVA")["customer_code"] == "C0078"
    assert customers.resolve(None, GOOD_GSTIN)["location"] == "Raipur plant"
    assert any(x["code"] == "C0078" for x in ok(c.get("/api/customers")))
    rv = revisions("customer", "C0078")
    assert [r["action"] for r in rv] == ["create"] and rv[0]["before"] is None
    assert audits("customer.create")[-1]["entity_id"] == "C0078"


@test("a rename keeps the old name as one of the customer's names: the allocation Planning "
      "wrote under it shows the NEW name, a filter still finds it, Search & Trace still counts "
      "it - and an edit that changes nothing writes nothing")
def t_rename_keeps_old_name():
    c = T.setup()
    line = custom_indent(c, "REN-01", "Srvs Solars Limited", "ISEN625-G12R")
    ok(allocate(c, line, ["SRVS0001", "SRVS0002"]))
    with store.conn() as (cx, cur):
        stored = store.one(cur, "SELECT customer FROM allocation")["customer"]
    assert stored == "Srvs Solars Limited", stored        # Planning stores the NAME
    body = {"name": "SRVS Solars Ltd", "gstins": ["22AACCP9830A1ZV"],
            "aliases": ["SRVS SOLARS", "SRVS"], "state": "Chhattisgarh"}
    d = ok(c.put("/api/customer/C0005", json=body))
    assert d["changed"] and d["customer"]["former_names"] == ["Srvs Solars Limited"], d
    assert customers.get("Srvs Solars Limited")["customer_code"] == "C0005"
    assert [a["customer"] for a in ok(c.get("/api/allocations"))] == ["SRVS Solars Ltd"]
    sql, args = db.customer_match("customer", "SRVS Solars Ltd")
    with store.conn() as (cx, cur):
        n = store.one(cur, "SELECT COUNT(*) AS n FROM serial WHERE " + sql, args)["n"]
    assert n == 2, "the filter lost the modules written under the old name"
    tr = ok(c.get("/api/trace/find", query_string={"q": "SRVS SOLARS LTD", "kind": "customer"}))
    assert tr.get("kind") == "customer" and len(tr["batches"]) == 1, tr
    rv = revisions("customer", "C0005")
    assert rv[-1]["action"] == "edit"
    assert (rv[-1]["before"]["name"], rv[-1]["after"]["name"]) == \
        ("Srvs Solars Limited", "SRVS Solars Ltd")
    n_rev = len(rv)
    again = ok(c.put("/api/customer/C0005", json=body))
    assert again["changed"] is False and len(revisions("customer", "C0005")) == n_rev


@test("a packing list prints the master's CURRENT name; a challan keeps the invoice's text "
      "it was made with - before and after the customer is renamed")
def t_documents_after_rename():
    c = T.setup()
    box = T.packed_box(c, [0, 1], customer="C0001")
    sheet = "/box/%d/sheet" % box
    h = c.get(sheet).get_data(as_text=True)
    assert "Agni Green Power Limited (Mz)" in h, "the packing list does not name the customer"
    path, no = TP.loaded_challan(c, [T.packed_box(c, [5, 6], customer=None)], 2)
    before = c.get(path).get_data(as_text=True)
    assert "AGNI GREEN POWER LIMITED" in before.upper()
    ok(c.put("/api/customer/C0001", json={"name": "Agni Renewables Ltd",
                                          "gstins": ["15AACCA2122Q1ZT"],
                                          "aliases": ["AGNI GREEN POWER LIMITED",
                                                      "AGNI GREEN POWER", "AGNI"],
                                          "state": "Mizoram"}))
    h = c.get(sheet).get_data(as_text=True)
    assert "Agni Renewables Ltd" in h and "Agni Green Power Limited (Mz)" not in h, \
        "the packing list did not take the current name"
    after = c.get(path).get_data(as_text=True)
    assert "Agni Renewables Ltd" not in after, "the challan was rewritten with the master's name"
    assert "AGNI GREEN POWER LIMITED" in after.upper(), "the challan lost the invoice's text"


@test("a code is never changed, nor a model's family; the refusal says why")
def t_keys_fixed():
    c = T.setup()
    refused(c.put("/api/customer/C0005", json={"code": "C0099", "name": "Srvs Solars Limited"}),
            400, "never changed", "C0005")
    m = ok(c.get("/api/admin/models"))["models"]
    row = next(x for x in m if x["model"] == "ISEN625-G12R")
    refused(c.put("/api/model/ISEN625-G12R", json=dict(row, model="ISEN626-G12R")),
            400, "code is never changed")
    refused(c.put("/api/model/ISEN625-G12R", json=dict(row, family="G2X")),
            400, "family is fixed", "F0201")
    refused(c.put("/api/model/ISEN625-G12R", json=dict(row, wattage=630)),
            400, "ISEN625-G12R says 625 W, the wattage says 630 W")
    d = ok(c.put("/api/model/ISEN625-G12R", json=dict(row, erp_code="F01030099",
                                                      produced=True)))
    assert d["changed"] and d["model"]["erp_code"] == "F01030099"


@test("a removed row is not edited - 409, naming who removed it and when")
def t_removed_not_edited():
    c = T.setup()
    ok(c.delete("/api/customer/C0010", json={"reason": "test"}))
    why = refused(c.put("/api/customer/C0010", json={"name": "Anything"}), 409,
                  "was removed from the customer master on", "Restore it first")
    assert re.search(r"on \d\d-\d\d-\d{4} by \S+", why), why
    ok(c.delete("/api/model/ISEN615-G12R", json={"reason": "test"}))
    refused(c.put("/api/model/ISEN615-G12R", json={"cells": 132}), 409,
            "was removed from the model master on")


@test("removing a customer an indent and an allocation name: the use-check says so first; "
      "afterwards the allocation still names it, nothing new is matched to it (an indent, a "
      "new batch, a picker), and a restore puts it back")
def t_remove_customer_in_use():
    c = T.setup()
    name = "Ravitya Solar Energy LLP - (MH)"
    line = custom_indent(c, "RAV-01", name, "ISEN625-G12R")
    ok(allocate(c, line, ["RAV0001", "RAV0002", "RAV0003", "RAV0004"]))
    u = ok(c.get("/api/customer/C0003/use"))
    assert (u["indents"], u["to_plan"], u["modules"], u["in_flight"]) == (1, 6, 4, 4), u
    assert u["open"] == [{"indent_no": "RAV-01", "left": 6}], u
    refused(c.delete("/api/customer/C0003", json={}), 400, "reason is required")
    d = ok(c.delete("/api/customer/C0003", json={"reason": "merged into another code"}))
    assert d["to_plan"] == 6 and d["modules"] == 4
    assert [a["customer"] for a in ok(c.get("/api/allocations"))] == [name], \
        "the allocation stopped naming the removed customer"
    assert customers.resolve(name) is None and customers.get("C0003")["removed_at"]
    assert not any(x["code"] == "C0003" for x in ok(c.get("/api/customers")))
    item = models.get_item("ISEN625-G12R-DCR")["item_code"]
    r = c.post("/api/indent", json={"indent_no": "RAV-02", "indent_date": "2026-10-02",
               "customer": name, "items": [{"item_code": item, "qty": 5}]}).get_json()
    assert any("was removed from the customer master" in e for e in r.get("errors", [])), r
    refused(allocate(c, line, ["RAV0005"]), 400, "was removed from the customer master")
    # an edit of the indent that already names it keeps it
    r = c.put("/api/indent/RAV-01", json={"customer": name, "indent_date": "2026-10-01",
              "items": [{"item_code": item, "qty": 10}]}).get_json()
    assert r.get("ok"), r
    refused(c.post("/api/customer/C0003/restore", json={}), 400, "reason is required")
    ok(c.post("/api/customer/C0003/restore", json={"reason": "the merge was undone"}))
    assert customers.resolve(name)["customer_code"] == "C0003"
    ok(allocate(c, line, ["RAV0005"]))
    assert [r["action"] for r in revisions("customer", "C0003")] == ["remove", "restore"]
    assert audits("customer.remove") and audits("customer.restore")


@test("a removed customer's GSTIN is never put on another customer - new, or an edit adding "
      "it - and the 'unknown' answer for it says it was removed: it is restored, never added "
      "under a second code; a restore is still refused if another customer holds its GSTIN")
def t_removed_gstin_not_added_again():
    c = T.setup()
    ok(c.delete("/api/customer/C0004", json={"reason": "gone quiet"}))
    # months later its invoice arrives with the name printed a little differently
    refused(c.post("/api/customer", json={"name": "Agrawal Channel Mills Pvt Ltd (new)",
                                          "gstins": ["22AAFCA7929N1ZC"]}), 400,
            "22AAFCA7929N1ZC is the GSTIN of Agrawal Channel Mills Private Limited (C0004), "
            "removed from the customer master on", "restore it in Admin > Customers")
    refused(c.put("/api/customer/C0005", json={"gstins": ["22AACCP9830A1ZV",
                                                          "22AAFCA7929N1ZC"]}), 400,
            "is the GSTIN of Agrawal Channel Mills Private Limited (C0004)")
    for q in ({"gstin": "22AAFCA7929N1ZC", "name": "Agrawal Channel Mill"},
              {"name": "AGRAWAL CHANNEL MILLS"}):
        d = ok(c.get("/api/customers/resolve", query_string=q))
        assert d["found"] is False and d["unknown"]["removed"]["code"] == "C0004", d
        assert "restore it in Admin > Customers" in d["unknown"]["removed"]["why"], d
    assert "removed" not in ok(c.get("/api/customers/resolve",
                                     query_string={"name": "Nobody Solar"}))["unknown"]
    ok(c.post("/api/customer/C0004/restore", json={"reason": "it was not gone"}))
    assert customers.resolve(None, "22AAFCA7929N1ZC")["customer_code"] == "C0004"
    # data written before the rule (or by hand) can still collide: Restore says so
    ok(c.delete("/api/customer/C0004", json={"reason": "test"}))
    with store.conn() as (cx, cur):
        cur.execute("UPDATE customer SET gstins=%s WHERE customer_code='C0005'",
                    (json.dumps(["22AACCP9830A1ZV", "22AAFCA7929N1ZC"]),))
    store.load_masters()
    refused(c.post("/api/customer/C0004/restore", json={"reason": "test"}), 400,
            "22AAFCA7929N1ZC is Srvs Solars Limited's GSTIN now (C0005)")


@test("an invoice whose buyer was REMOVED from the master: the challan check says so - "
      "why only General Stock is offered, and the way back - and refuses the buyer's own "
      "pallet with the same reason")
def t_challan_buyer_removed():
    c = T.setup()
    box = T.packed_box(c, [0, 1], customer="C0001")
    inv = T.make_invoice(qty=2)                       # Agni's name and GSTIN
    ok(c.delete("/api/customer/C0001", json={"reason": "gone quiet"}))
    d = ok(c.post("/api/challan/checks", json={"boxes": [], "invoice_id": inv}))
    note = d["buyer_removed"]
    assert note and note["code"] == "C0001", d
    assert "removed from the customer master" in note["why"] and "restore it" in note["why"], note
    d = ok(c.post("/api/challan/checks", json={"boxes": [box], "invoice_id": inv}))
    owner = [b["detail"] for b in d["blocking"] if b["code"] == "E-OWNER"]
    assert owner and "Agni Green Power Limited (Mz) (C0001), removed from the customer master" \
        in owner[0] and "until it is restored" in owner[0], d["blocking"]
    ok(c.post("/api/customer/C0001/restore", json={"reason": "it was not gone"}))
    d = ok(c.post("/api/challan/checks", json={"boxes": [box], "invoice_id": inv}))
    assert d["buyer_removed"] is None and not [b for b in d["blocking"]
                                              if b["code"] == "E-OWNER"], d["blocking"]


@test("Icon Stock is never removed - it is the 'unallocated' value, not a customer")
def t_stock_never_removed():
    c = T.setup()
    refused(c.delete("/api/customer/STOCK", json={"reason": "tidy up"}), 400,
            "not a customer", "cannot be removed")
    assert not customers.get("STOCK")["removed_at"]


@test("a new model takes the next item codes of its family, and is refused when its code "
      "and wattage disagree, its family has no serial type character, another live model "
      "has its wattage and family, or its cells do not add up")
def t_model_create():
    c = T.setup()
    base = {"model": "ISEN640-G12R", "wattage": 640, "family": "G12R", "cells": 132,
            "cells_per_string": 22, "strings": 6}
    refused(c.post("/api/model", json=dict(base, wattage=645)), 400,
            "ISEN640-G12R says 640 W, the wattage says 645 W")
    refused(c.post("/api/model", json=dict(base, model="ISEN640-TOPCON", family="TOPCON")),
            400, "The family must be one of")
    refused(c.post("/api/model", json=dict(base, strings=5)), 400, "22 cells per string x 5")
    refused(c.post("/api/model", json=dict(base, model="ISEN625-G12R", wattage=625)), 400,
            "already in the master")
    d = ok(c.post("/api/model", json=base))
    assert d["model"]["tc"] == "R"
    codes = sorted(i["item_code"] for i in models.all_items() if i["model"] == "ISEN640-G12R")
    assert codes == ["F02010017", "F02010018"], codes
    assert "F02010017" in json.loads(models.items_json())
    refused(c.post("/api/model", json=dict(base, model="BRAND640-G12R")), 400,
            "ISEN640-G12R is already 640 W G12R", "ICON640R")
    assert revisions("model", "ISEN640-G12R")[0]["action"] == "create"


@test("a model whose serials exist may be removed: the use-check leads with what is still to "
      "plan; afterwards nothing new is planned on it - while its indent keeps its line and its "
      "modules are packed as before - until it is restored")
def t_remove_model_in_use():
    c = T.setup()
    line = custom_indent(c, "M625-01", "Borosil Renewables Limited", "ISEN625-G12R")
    ok(allocate(c, line, ["BRS0001", "BRS0002", "BRS0003", "BRS0004"]))
    u = ok(c.get("/api/model/ISEN625-G12R/use"))
    assert u["to_plan"] == 6 and u["open"] == [{"indent_no": "M625-01", "line": 1,
                                                "left": 6, "qty": 10}], u
    assert (u["serials"], u["not_produced"], u["batches"]) == (4, 4, 1), u
    refused(c.delete("/api/model/ISEN625-G12R", json={}), 400, "reason is required")
    ok(c.delete("/api/model/ISEN625-G12R", json={"reason": "replaced by ISEN625-G12R-V2"}))
    assert not any(i["model"] == "ISEN625-G12R" for i in models.all_items())
    assert models.get("ISEN625-G12R")["removed_at"] and models.defaults_for("ISEN625-G12R") is None
    item = models.get_item("ISEN625-G12R-DCR")["item_code"]
    r = c.post("/api/indent", json={"indent_no": "M625-02", "indent_date": "2026-10-02",
               "customer": "Borosil Renewables Limited",
               "items": [{"item_code": item, "qty": 5}]}).get_json()
    assert any("was removed from the model master" in e for e in r.get("errors", [])), r
    r = c.put("/api/indent/M625-01", json={"customer": "Borosil Renewables Limited",
              "indent_date": "2026-10-01", "delivery_text": "by month end",
              "items": [{"item_code": item, "qty": 10}]}).get_json()
    assert r.get("ok"), r                               # the line it already had stays
    refused(allocate(c, line, ["BRS0005"]), 400, "was removed from the model master",
            "Admin > Models")
    b = c.post("/api/box/open", json={"grade": "A", "model": "ISEN625-G12R",
                                      "capacity": 4}).get_json()
    assert b.get("box_id"), b                           # its modules still pack
    ok(c.post("/api/model/ISEN625-G12R/restore", json={"reason": "V2 was never released"}))
    ok(allocate(c, line, ["BRS0005"]))


@test("a model's restore is refused while another live model has its wattage and family")
def t_model_restore_twin():
    c = T.setup()
    ok(c.delete("/api/model/ISEN610-G12R", json={"reason": "test"}))
    ok(c.post("/api/model", json={"model": "BRAND610-G12R", "wattage": 610, "family": "G12R",
                                  "cells": 132, "cells_per_string": 22, "strings": 6}))
    refused(c.post("/api/model/ISEN610-G12R/restore", json={"reason": "test"}), 400,
            "BRAND610-G12R is 610 W G12R now", "Remove BRAND610-G12R first")


@test("every create, edit, removal and restore is a revision with the row before and after, "
      "read back by the history route")
def t_history():
    c = T.setup()
    code = ok(c.post("/api/customer", json={"name": "History Test Co", "aliases": ["HTC"],
                                            "gstins": [GOOD_GSTIN]}))["code"]
    # a PUT of the name alone keeps what it did not send
    d = ok(c.put("/api/customer/%s" % code, json={"name": "History Test Company"}))
    assert d["customer"]["aliases"] == ["HTC"] and d["customer"]["gstins"] == [[GOOD_GSTIN, None]], d
    ok(c.delete("/api/customer/%s" % code, json={"reason": "test"}))
    ok(c.post("/api/customer/%s/restore" % code, json={"reason": "test"}))
    h = ok(c.get("/api/customer/%s/history" % code))["revisions"]
    assert [r["action"] for r in h] == ["restore", "remove", "edit", "create"], h
    edit = h[2]
    assert edit["before"]["name"] == "History Test Co" and \
        edit["after"]["former_names"] == ["History Test Co"], edit
    assert h[1]["after"]["removed_reason"] == "test" and h[0]["after"]["removed_at"] is None


@test("an Admin reads both masters and is refused every write; an operator reads neither")
def t_gates():
    T.setup()
    a = APP.app.test_client()
    AUTH.test_login(a, role="Admin", login_id="adm.master")
    ok(a.get("/api/admin/customers"))
    ok(a.get("/api/admin/models"))
    for r in (a.post("/api/customer", json={"name": "X Co"}),
              a.put("/api/customer/C0005", json={"name": "X"}),
              a.delete("/api/customer/C0005", json={"reason": "x"}),
              a.post("/api/model", json={}), a.delete("/api/model/ISEN625-G12R",
                                                      json={"reason": "x"})):
        assert r.status_code == 403, r.status_code
    p = APP.app.test_client()
    AUTH.test_login(p, role="Packing Operator", login_id="pack.master")
    assert p.get("/api/admin/customers").status_code == 403
    assert p.get("/api/admin/models").status_code == 403


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    width = max(len(n) for n, _ in _results)
    passed = failed = 0
    for name, fn in _results:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
            print("  PASS  %-*s" % (width, name))
            passed += 1
        except Exception as e:
            print("  FAIL  %-*s  %s" % (width, name, str(e)[:900]))
            if "-v" in sys.argv:
                traceback.print_exc()
            failed += 1
    print("\n%d passed, %d failed" % (passed, failed))
    import shutil
    shutil.rmtree(T.TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
