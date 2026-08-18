#!/usr/bin/env python3
"""A股个股快照构建: 股票池=data/equity.json 的56品种权益篮子(135只)。
数据源: 东方财富 push2/push2his(免费, 无需key)。
产出: data/stocks/quotes.json(指数+个股行情+板块聚合) + data/stocks/kline/{code}.json(日K+MA+MACD+RSI)。
失败容忍: 单票失败跳过并标记, 不阻断站点构建。"""
from __future__ import annotations
import json, math, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "stocks"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch(url: str, retries: int = 3) -> dict | None:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def secid(code: str) -> str:
    return ("1." if code.startswith("sh") else "0.") + code[2:]


def ema(vals, n):
    out, k = [], 2 / (n + 1)
    e = None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    gains, losses = 0.0, 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains = (gains * (n - 1) + max(ch, 0)) / n
        losses = (losses * (n - 1) + max(-ch, 0)) / n
        if i >= n:
            out[i] = round(100 - 100 / (1 + gains / losses), 1) if losses else 100.0
    return out


def ma(vals, n):
    return [round(sum(vals[max(0, i - n + 1):i + 1]) / min(i + 1, n), 2) if i >= n - 1 else None for i in range(len(vals))]


def build_kline(code: str) -> dict | None:
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           "?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56"
           "&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=1"
           f"&secid={secid(code)}&beg=20250101&end=20500101")
    d = fetch(url)
    kl = ((d or {}).get("data") or {}).get("klines") or []
    if len(kl) < 30:
        return None
    bars = []
    for line in kl:
        p = line.split(",")
        bars.append({"t": p[0], "o": float(p[1]), "c": float(p[2]), "h": float(p[3]), "l": float(p[4]), "v": float(p[5])})
    closes = [b["c"] for b in bars]
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [round(a - b, 3) for a, b in zip(e12, e26)]
    dea = [round(v, 3) for v in ema(dif, 9)]
    macd = [round(2 * (a - b), 3) for a, b in zip(dif, dea)]
    return {"bars": bars, "ma5": ma(closes, 5), "ma20": ma(closes, 20), "ma60": ma(closes, 60),
            "dif": dif, "dea": dea, "macd": macd, "rsi": rsi(closes)}


def main() -> None:
    eq = json.loads((ROOT / "data" / "equity.json").read_text(encoding="utf-8"))
    products = eq.get("products") or {}
    pool = {}  # code -> {name, sectors}
    for sym, info in products.items():
        for s in info.get("stocks") or []:
            e = pool.setdefault(s["code"], {"code": s["code"], "name": s["name"], "sectors": set()})
            e["sectors"].add(sym)
    codes = sorted(pool)
    print(f"[stocks] pool={len(codes)}")

    # 批量行情(单次最多~80只稳妥, 分2批)
    quotes = {}
    F = "f12,f14,f2,f3,f5,f6,f8,f9,f10,f20,f21,f62"
    for i in range(0, len(codes), 70):
        batch = codes[i:i + 70]
        secids = ",".join(secid(c) for c in batch)
        d = fetch(f"https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids={secids}&fields={F}")
        for it in ((d or {}).get("data") or {}).get("diff") or []:
            code = ("sh" if it.get("f13") == 1 else "sz") + str(it.get("f12"))
            quotes[code] = {
                "price": it.get("f2"), "chg": it.get("f3"), "vol": it.get("f5"),
                "amount": it.get("f6"), "turnover": it.get("f8"), "pe": it.get("f9"),
                "vol_ratio": it.get("f10"), "mktcap": it.get("f20"),
                "main_inflow": it.get("f62"),
            }
        time.sleep(0.8)

    # 指数
    indices = {}
    for sec, name in (("1.000001", "上证指数"), ("0.399001", "深证成指"), ("0.399006", "创业板指")):
        d = fetch(f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec}&fields=f43,f44,f45,f46,f60,f170")
        dd = (d or {}).get("data") or {}
        if dd:
            indices[name] = {"price": (dd.get("f43") or 0) / 100, "chg": (dd.get("f170") or 0) / 100}
        time.sleep(0.5)

    # 板块聚合(按品种): 篮子等权涨跌
    sectors = {}
    for sym, info in products.items():
        got = [quotes[s["code"]] for s in info.get("stocks") or [] if quotes.get(s["code"], {}).get("chg") is not None]
        if got:
            sectors[sym] = {
                "chg": round(sum(q["chg"] for q in got) / len(got), 2), "n": len(got),
                "inflow": round(sum((q.get("main_inflow") or 0) for q in got) / 1e8, 2),
                "hot_n": sum(1 for q in got if (q.get("vol_ratio") or 0) >= 1.5),
            }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "kline").mkdir(exist_ok=True)
    ok = 0
    for c in codes:
        kf = OUT / "kline" / f"{c}.json"
        if kf.exists() and (time.time() - kf.stat().st_mtime) < 20 * 3600:
            ok += 1
            continue  # 增量: 20小时内已有K线则跳过
        k = build_kline(c)
        if k:
            k["code"] = c
            k["name"] = pool[c]["name"]
            (OUT / "kline" / f"{c}.json").write_text(json.dumps(k, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            ok += 1
        time.sleep(0.35)

    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "indices": indices,
        "sectors": sectors,
        "stocks": [
            {**pool[c], "sectors": sorted(pool[c]["sectors"]), **quotes.get(c, {})}
            for c in codes
        ],
        "kline_ok": ok,
    }
    payload["stocks"] = [{**s, "sectors": s["sectors"]} for s in payload["stocks"]]
    (OUT / "quotes.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[stocks] quotes={len(quotes)} kline={ok}/{len(codes)}")


if __name__ == "__main__":
    main()
