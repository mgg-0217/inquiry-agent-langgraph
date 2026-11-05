from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Customer
from app.tools import comms, compliance, customer, pricing, product, registry


# ---------------------------------------------------------------- search_product


def test_search_product_hits_by_sku():
    res = product.search_product("X200")
    assert res["ok"] is True
    skus = [c["sku"] for c in res["data"]["candidates"]]
    assert skus == ["X200"]


def test_search_product_hits_by_category():
    res = product.search_product("pump")
    skus = {c["sku"] for c in res["data"]["candidates"]}
    assert skus == {"X200", "Z400"}


def test_search_product_with_specs_constraint():
    res = product.search_product("", {"voltage": "380V/50Hz"})
    skus = {c["sku"] for c in res["data"]["candidates"]}
    assert skus == {"X200", "Z400"}


def test_search_product_not_found():
    res = product.search_product("不存在的型号-999")
    assert res["ok"] is False
    assert res["code"] == "NOT_FOUND"


# ---------------------------------------------------------------- check_inventory


def test_check_inventory_in_stock():
    res = product.check_inventory("X200", 200)
    assert res["ok"] is True
    assert res["data"]["available"] is True
    assert res["data"]["lead_time"] == "25 days"


def test_check_inventory_large_qty_extends_lead_time():
    res = product.check_inventory("X200", 500)
    assert res["ok"] is True
    assert res["data"]["lead_time"] == "35 days"


def test_check_inventory_shortage():
    res = product.check_inventory("X200", 5000)
    assert res["ok"] is True
    assert res["data"]["available"] is False


def test_check_inventory_unknown_sku():
    res = product.check_inventory("NOPE", 1)
    assert res["ok"] is False
    assert res["code"] == "NOT_FOUND"


# ---------------------------------------------------------------- calc_price


def test_calc_price_cif_500_units_matches_prd():
    res = pricing.calc_price("X200", 500, "CIF", "Valencia")
    data = res["data"]
    assert res["ok"] is True
    assert data["applicable"]["unit_price"] == 350.0
    assert data["applicable"]["total"] == 175000.0
    assert data["floor_price"] == 338.0
    assert [t["unit_price"] for t in data["tiers"]] == [380.0, 364.0, 350.0]
    assert data["freight"] == 8.5
    assert data["insurance"] == 3.5
    assert data["valid_until"]


def test_calc_price_fob_120_units():
    res = pricing.calc_price("X200", 120, "FOB")
    data = res["data"]
    assert data["applicable"]["unit_price"] == 352.0
    assert data["applicable"]["total"] == 42240.0
    assert data["freight"] == 0.0
    assert data["insurance"] == 0.0


def test_calc_price_target_above_floor_is_matched():
    res = pricing.calc_price("X200", 300, "CIF", "Valencia", target_price=350.0)
    assert res["data"]["target_matched_price"] == 350.0


def test_calc_price_target_below_floor_returns_null():
    res = pricing.calc_price("X200", 300, "CIF", "Valencia", target_price=300.0)
    assert res["data"]["target_matched_price"] is None


def test_calc_price_default_incoterm_from_settings():
    res = pricing.calc_price("X200", 120)
    assert res["data"]["incoterm"] == settings.default_incoterm


def test_calc_price_invalid_incoterm():
    res = pricing.calc_price("X200", 10, "DDP")
    assert res["ok"] is False
    assert res["code"] == "INVALID_ARGUMENT"


def test_calc_price_invalid_qty():
    res = pricing.calc_price("X200", 0)
    assert res["ok"] is False
    assert res["code"] == "INVALID_ARGUMENT"


def test_calc_price_unknown_sku():
    res = pricing.calc_price("NOPE", 10)
    assert res["ok"] is False
    assert res["code"] == "NOT_FOUND"


# ---------------------------------------------------------------- lookup_customer


def test_lookup_customer_unknown_email_is_new():
    res = customer.lookup_customer("nobody@unknown.example")
    assert res["ok"] is True
    assert res["data"]["found"] is False
    assert res["data"]["is_new"] is True
    assert res["data"]["customer"] is None


def test_lookup_customer_hits_demo_profile(session: Session):
    res = customer.lookup_customer("carlos@acme-import.example", session=session)
    data = res["data"]
    assert data["found"] is True
    assert data["is_new"] is False
    assert data["customer"]["country"] == "ES"
    assert data["orders"][0]["lost_reason"] == "price_high"
    assert any(f["key"] == "target_price" for f in data["facts"])


def test_lookup_customer_hits_db_row(session: Session):
    row = Customer(email="db@acme-import.example", name="DB Customer")
    session.add(row)
    session.commit()

    res = customer.lookup_customer("db@acme-import.example", session=session)
    assert res["data"]["found"] is True
    assert res["data"]["is_new"] is False
    assert res["data"]["customer"]["id"] == row.id


# ---------------------------------------------------------------- compliance / translate


def test_screen_compliance_is_honest_about_unloaded_list(monkeypatch):
    import app.tools.compliance as mod

    monkeypatch.setattr(mod, "_index_cache", None)
    monkeypatch.setattr(mod, "load_from_db", lambda _session=None: [])
    res = mod.screen_compliance("Acme Import", "ES")
    assert res["ok"] is True
    assert res["data"]["hits"] == []
    # 名单没加载时不能宣称"通过"
    assert res["data"]["list_loaded"] is False
    assert "名单尚未加载" in res["message"]


def test_translate_is_passthrough_not_fake():
    res = comms.translate("你好", "en")
    assert res["ok"] is True
    assert res["data"]["text"] == "你好"
    assert res["data"]["provider"] == "passthrough"


# ---------------------------------------------------------------- send / schedule


def test_send_message_dry_run_does_not_send(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    res = comms.send_message("buyer@newco.example", "Quote", "body")
    assert res["ok"] is True
    assert res["data"]["dry_run"] is True
    assert res["code"] == "DRY_RUN"


def test_send_message_rejects_when_whitelist_empty(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "send_whitelist", "")
    res = comms.send_message("buyer@newco.example", "Quote", "body")
    assert res["ok"] is False
    assert res["code"] == "NOT_WHITELISTED"


def test_send_message_rejects_non_whitelisted(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "send_whitelist", "allowed@example.com")
    res = comms.send_message("buyer@newco.example", "Quote", "body")
    assert res["ok"] is False
    assert res["code"] == "NOT_WHITELISTED"


def test_send_message_sends_when_whitelisted(monkeypatch):
    class FakeProvider:
        def send(self, to, subject, body, **kwargs):
            return "<sent-123@test>"

    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(settings, "send_whitelist", "allowed@example.com")
    monkeypatch.setattr("app.tools.comms.build_provider", lambda: FakeProvider())

    res = comms.send_message("allowed@example.com", "Quote", "body")
    assert res["ok"] is True
    assert res["data"]["message_id"] == "<sent-123@test>"
    assert res["data"]["dry_run"] is False


def test_schedule_followup_not_implemented():
    res = comms.schedule_followup("thread-1")
    assert res["ok"] is False
    assert res["code"] == "NOT_IMPLEMENTED"


# ---------------------------------------------------------------- registry


def test_registry_exposes_six_read_and_two_write_tools():
    read = registry.build_read_tools()
    write = registry.build_write_tools()

    read_names = {t.name for t in read}
    assert read_names == {
        "search_product",
        "check_inventory",
        "calc_price",
        "lookup_customer",
        "screen_compliance",
        "translate",
    }
    assert {t.name for t in write} == {"send_message", "schedule_followup"}
    # 写工具不能出现在模型可见列表里
    assert not (read_names & {t.name for t in write})


def test_registry_tools_are_invocable():
    tools = {t.name: t for t in registry.build_read_tools()}

    price = tools["calc_price"].invoke(
        {"sku": "X200", "qty": 120, "incoterm": "CIF", "destination": "Valencia"}
    )
    assert price["ok"] is True
    assert price["data"]["applicable"]["unit_price"] == 364.0

    found = tools["search_product"].invoke({"keyword": "X200"})
    assert found["data"]["candidates"][0]["sku"] == "X200"


def test_export_schemas_lists_all_eight():
    schemas = registry.export_schemas()
    assert len(schemas) == 8
    calc = next(s for s in schemas if s["name"] == "calc_price")
    assert "sku" in calc["args_schema"]["properties"]
