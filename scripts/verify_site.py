#!/usr/bin/env python3
"""Fail CI when a published site is incomplete or exposes a secret."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "_site"
market = json.loads((SITE / "data" / "market.json").read_text(encoding="utf-8"))
products = market.get("products") or []
assert market.get("total_supported") == 76, market.get("total_supported")
assert market.get("total_published") == 76, market.get("total_published")
assert len(products) == 76, len(products)
assert len({item["symbol"] for item in products}) == 76
for item in products:
    path = SITE / "data" / "symbols" / f"{item['symbol']}.json"
    assert path.is_file(), path
    detail = json.loads(path.read_text(encoding="utf-8"))
    volatility = detail.get("volatility") or {}
    if volatility.get("vol20") is not None and volatility.get("vol60") is not None:
        expanding = float(volatility["vol20"]) > float(volatility["vol60"])
        assert volatility.get("trend") == ("扩张" if expanding else "收缩"), (item["symbol"], volatility)
        regime = str(volatility.get("regime") or "")
        assert ("扩张" in regime or "启动" in regime) if expanding else ("收缩" in regime or "收敛" in regime), (item["symbol"], volatility)
    assert set(detail["frameworks"]) == {"ari", "chan", "macd", "gann"}
    assert set(detail["decision"]) >= {"left_long", "left_short"}
    for plan in (detail["decision"], *(detail.get("strategies") or {}).values()):
        assert len(plan["left_long"]["zone"]) == 2
        assert len(plan["left_short"]["zone"]) == 2
    assert detail["decision"].get("confidence") in {"完整多周期", "降级观察"}
    if item["symbol"] in {"JD", "AG", "MA", "RB"}:
        assert set(detail.get("charts") or {}) == {"W", "D", "60", "15"}
        assert set(detail.get("strategies") or {}) == {"W", "D", "60", "15"}
        assert set(detail.get("data_quality") or {}) == {"W", "D", "60", "15"}
fundamentals = json.loads((SITE / "data" / "fundamentals.json").read_text(encoding="utf-8"))
assert fundamentals.get("schema_version") == 3
focus = fundamentals.get("products") or []
assert fundamentals.get("coverage", {}).get("total") == 76
assert fundamentals.get("coverage", {}).get("focus") == 62
assert len(focus) == 76
deep = [item for item in focus if item.get("kind") == "focus"]
assert len(deep) == 62
assert all(2 <= len(item.get("metrics") or []) <= 3 for item in deep)
coverage = fundamentals.get("coverage") or {}
assert sum(int(coverage.get(key) or 0) for key in ("ready", "observe", "blocked")) == 76
for item in focus:
    assert item.get("maturity") in {"placeholder", "draft", "reviewed", "deep"}
    assert item.get("decision_status") in {"ready", "observe", "blocked"}
    quality = item.get("quality") or {}
    assert quality.get("decision_status") == item.get("decision_status")
    if item.get("kind") == "focus":
        assert item.get("falsifier"), item.get("symbol")
        for metric in item.get("metrics") or []:
            assert metric.get("role") in {"leading", "synchronous", "falsifier"}
            assert metric.get("mapping_quality") in {"exact", "transform", "proxy", "unverified"}
    if item.get("decision_status") == "ready":
        assert not quality.get("reasons"), item.get("symbol")
        assert all(not metric.get("stale") for metric in item.get("metrics") or [])
        assert all(metric.get("status") == "ok" for metric in item.get("metrics") or [])
        assert all(metric.get("mapping_quality") in {"exact", "transform"} for metric in item.get("metrics") or [])
    if item.get("decision_status") == "blocked":
        assert (item.get("tradability") or {}).get("status") == "disabled"
fundamental_raw = json.dumps(fundamentals, ensure_ascii=False)
assert '"score"' not in fundamental_raw
assert '"consistency"' not in fundamental_raw
assert "fundamentalCard" in (SITE / "index.html").read_text(encoding="utf-8")
assert (SITE / "auth.js").is_file()
manifest = json.loads((SITE / "manifest.webmanifest").read_text(encoding="utf-8"))
assert manifest.get("display") == "standalone"
assert manifest.get("start_url") == "./#radar"
assert {icon["sizes"] for icon in manifest.get("icons", [])} >= {"192x192", "512x512"}
assert (SITE / "sw.js").is_file()
assert "serviceWorker.register('./sw.js')" in (SITE / "app.js").read_text(encoding="utf-8")
assert "LEFT-SIDE WATCHLIST" in (SITE / "index.html").read_text(encoding="utf-8")
for name in ("app-icon-192.png", "app-icon-512.png", "apple-touch-icon.png", "favicon-32.png"):
    assert (SITE / "assets" / name).stat().st_size > 1_000, name
assert "windowState" in (SITE / "auth.js").read_text(encoding="utf-8")  # 2026-08-18 撤密码门后仅校验结构存在
assert (SITE / "robots.txt").read_text(encoding="utf-8").strip().endswith("Noindex: /")
macro = json.loads((SITE / "data" / "macro.json").read_text(encoding="utf-8"))
ev = macro.get("event", {})
assert ev.get("title") and ev.get("conclusion") and ev.get("stance"), "macro.json event 需含 title/conclusion/stance"
for path in SITE.rglob("*"):
    if path.is_file() and path.suffix.lower() in {".html", ".js", ".css", ".json", ".md", ".txt"}:
        assert "wk_" not in path.read_text(encoding="utf-8", errors="ignore"), path
assert (SITE / "assets" / "abyss-voyage-cover.png").stat().st_size > 100_000
print("site verification: 76/76 four-timeframe strategies, access gate, fundamentals, macro and secret scan OK")
