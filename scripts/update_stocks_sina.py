#!/usr/bin/env python3
"""A股板块涨跌幅·sina 直连快更（2026-08-20 建）。

eastmoney 从 US runner/断网时不可靠；本脚本用 sina(hq.sinajs.cn) 实时行情，
只更新 quotes.json 的 sectors(板块篮子等权涨跌)+个股 price/chg，约 10s 完成。
供本地 _ff_sync15.py 日盘 15min 调用；全量(市值/PE/K线)仍由 build_stocks 每日补。
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "stocks"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def main() -> int:
    eq = json.loads((ROOT / "data" / "equity.json").read_text(encoding="utf-8"))
    products = eq.get("products") or {}
    pool: dict = {}
    for sym, info in products.items():
        for s in info.get("stocks") or []:
            e = pool.setdefault(s["code"], {"code": s["code"], "name": s["name"], "sectors": set()})
            e["sectors"].add(sym)
    codes = sorted(pool)
    print(f"[sina-stocks] pool={len(codes)}")

    quotes: dict = {}
    for i in range(0, len(codes), 60):
        batch = codes[i:i + 60]
        url = "https://hq.sinajs.cn/list=" + ",".join(batch)
        req = urllib.request.Request(url, headers={**UA, "Referer": "https://finance.sina.com.cn/"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                text = r.read().decode("gbk", errors="replace")
        except Exception as exc:
            print(f"batch err: {exc}")
            continue
        for line in text.splitlines():
            if "hq_str_" not in line:
                continue
            rest = line.split("hq_str_", 1)[1]
            sym, _, val = rest.partition("=")
            parts = val.strip('"').split(",")
            if len(parts) < 4:
                continue
            try:
                prev_close = float(parts[2])
                cur = float(parts[3])
                chg = round((cur - prev_close) / prev_close * 100, 2) if prev_close else None
            except ValueError:
                continue
            quotes[sym.strip()] = {"price": cur, "chg": chg}
        time.sleep(0.3)
    print(f"[sina-stocks] quotes={len(quotes)}")

    sectors: dict = {}
    for sym, info in products.items():
        got = [
            quotes[s["code"]]
            for s in info.get("stocks") or []
            if s["code"] in quotes and quotes[s["code"]].get("chg") is not None
        ]
        if got:
            sectors[sym] = {"chg": round(sum(q["chg"] for q in got) / len(got), 2), "n": len(got)}
    print(f"[sina-stocks] sectors={len(sectors)}")

    old = {}
    if (OUT / "quotes.json").exists():
        old = json.loads((OUT / "quotes.json").read_text(encoding="utf-8"))
    old["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    old["sectors"] = sectors
    old["source"] = "sina直连·本地快更"
    for st in old.get("stocks") or []:
        c = st.get("code")
        if c and c in quotes:
            st["price"] = quotes[c]["price"]
            st["chg"] = quotes[c]["chg"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "quotes.json").write_text(json.dumps(old, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("[sina-stocks] quotes.json written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
