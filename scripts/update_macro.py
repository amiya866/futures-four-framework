#!/usr/bin/env python3
"""宏观快报·离线自动更新（GitHub Actions / 本地均可跑，不依赖 agent）

逻辑：
  1. 读 data/macro.json 当前 event（title/updated_at）→ 判断已覆盖到哪个数据月。
  2. 按宏观日历找下一个已到期(release 时间已过)且 FRED 已有数据的事件。
  3. 生成该事件快报（FRED 实际值 + 宏观框架模板）→ 覆盖 data/macro.json。
  4. 无新事件 → 退出 0，不改文件。

数据源：FRED CSV（免 key）：
  CPI=CPIAUCSL / 核心CPI=CPILFESL / PCE=PCEPI / 核心PCE=PCEPILFE
  PPI(最终需求)=PPIFIS / 核心PPI(最终需求除食品能源贸易)=WPSFD49116
  非农=PAYEMS / 失业率=UNRATE
  美债收益率(日度)=DGS2/DGS5/DGS10/DGS30 / 欧洲央行存款便利利率=ECBDFR
框架：总量 vs 核心、环比边际、同比趋势 → Fed路径(加息紧迫性/降息门槛) → 金银传导(实际利率)。

外加两类监控：
  1. 美债 2/5/10/30 年收益率破位（日度）：最新收盘突破前 60 个交易日高/低点 → 生成破位快报。
     每期限每方向每月只报一次（covered 键 ust:SID:方向:YYYY-MM）；当前快报发布不足 20h 时不抢版。
  2. 欧洲央行利率决议：决议在 ECB_DECISIONS 有记录才自动生成（FRED 的 ECBDFR 生效日滞后，
     无法当天判定结果）；无记录则同 FOMC 留给人工。
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "data" / "macro.json"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"

# 2026 宏观日历（release_date 近似，随实际可改；data_month 为数据所属月）
CALENDAR = [
    ("2026-08-28", "pce", "2026-07", "美国7月PCE"),
    ("2026-09-04", "nonfarm", "2026-08", "美国8月非农"),
    ("2026-09-10", "ppi", "2026-08", "美国8月PPI"),
    ("2026-09-11", "cpi", "2026-08", "美国8月CPI"),
    ("2026-09-15", "fomc", "2026-09", "9月FOMC"),          # 决策型，需人工核对
    ("2026-09-10", "ecb", "2026-09", "欧洲央行9月利率决议"),
    ("2026-10-29", "ecb", "2026-10", "欧洲央行10月利率决议"),
    ("2026-12-17", "ecb", "2026-12", "欧洲央行12月利率决议"),
    ("2026-09-25", "pce", "2026-08", "美国8月PCE"),
    ("2026-10-02", "nonfarm", "2026-09", "美国9月非农"),
    ("2026-10-12", "ppi", "2026-09", "美国9月PPI"),
    ("2026-10-13", "cpi", "2026-09", "美国9月CPI"),
    ("2026-10-27", "fomc", "2026-10", "10月FOMC"),
    ("2026-10-30", "pce", "2026-09", "美国9月PCE"),
    ("2026-11-06", "nonfarm", "2026-10", "美国10月非农"),
    ("2026-11-10", "ppi", "2026-10", "美国10月PPI"),
    ("2026-11-12", "cpi", "2026-10", "美国10月CPI"),
    ("2026-11-25", "pce", "2026-11", "美国11月PPI"),
    ("2026-12-04", "nonfarm", "2026-11", "美国11月非农"),
    ("2026-12-08", "fomc", "2026-12", "12月FOMC"),
    ("2026-12-09", "ppi", "2026-11", "美国11月PPI"),
    ("2026-12-10", "cpi", "2026-11", "美国11月CPI"),
]


# 欧洲央行决议记录（决议后人工补录；FRED ECBDFR 生效日滞后，无法当天自动判定）
ECB_DECISIONS = {
    "2026-09-10": {
        "change_bp": 25,
        "deposit": 2.50, "mro": 2.65, "mlf": 2.90,
        "effective": "2026-09-16",
        "note": "年内第二次加息25bp；不预设固定加息路径，逐次会议数据依赖；APP与PEPP到期本金不再再投资；会后市场定价12月存款利率2.80%（声明前2.74%）→年内再加息预期升温。",
    },
}

# 美债收益率破位监控（日度，期限: FRED series）
UST_SERIES = {"2年期": "DGS2", "5年期": "DGS5", "10年期": "DGS10", "30年期": "DGS30"}
UST_LOOKBACK = 60        # 前 60 个交易日区间
UST_MIN_EVENT_AGE_H = 20  # 当前快报发布不足此时长不抢版


def _urlopen_retry(req: Request, timeout: int = 25, tries: int = 3) -> str:
    import time
    last = None
    for i in range(tries):
        try:
            with urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def fetch_fred(series_id: str) -> list[tuple[str, float]]:
    """返回 [(YYYY-MM, value)]，升序。"""
    url = FRED.format(id=series_id)
    req = Request(url, headers={"User-Agent": "macro-auto/1.0"})
    text = _urlopen_retry(req, timeout=45)
    rows: list[tuple[str, float]] = []
    for line in text.strip().splitlines()[1:]:
        if not line or "," not in line:
            continue
        d, v = line.split(",", 1)
        try:
            val = float(v)
        except ValueError:
            continue
        rows.append((d[:7], val))  # 归一化到 YYYY-MM，与日历 data_month 对齐
    return rows


def get_series(series_id: str) -> list[tuple[str, float]]:
    return fetch_fred(series_id)


def latest_month(rows: list[tuple[str, float]]) -> tuple[str, float]:
    return rows[-1] if rows else ("", math.nan)


def mom_yoy(rows: list[tuple[str, float]], target: str) -> dict:
    """对目标月算环比/同比。rows 为 [(date, val)]。"""
    idx = {d: v for d, v in rows}
    out = {"month": target, "value": idx.get(target, math.nan)}
    y, m = target.split("-")
    pm = f"{y}-{int(m)-1:02d}" if int(m) > 1 else f"{int(y)-1}-12"
    py = f"{int(y)-1}-{m}"
    prev = idx.get(pm, math.nan)
    prev_y = idx.get(py, math.nan)
    v = out["value"]
    out["mom"] = round((v / prev - 1) * 100, 2) if not math.isnan(prev) and prev else math.nan
    out["yoy"] = round((v / prev_y - 1) * 100, 2) if not math.isnan(prev_y) and prev_y else math.nan
    out["prev"] = prev
    return out


def pct(v: float) -> str:
    return f"{v:+.2f}%" if not math.isnan(v) else "—"


def read_macro() -> dict:
    if MACRO.exists():
        try:
            return json.loads(MACRO.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated_at": "", "event": {}}


def coverage_key(macro: dict) -> str:
    """从当前 event 的 metrics 里找已覆盖的数据月（month 字段）。"""
    for m in (macro.get("event") or {}).get("metrics") or []:
        if m.get("month"):
            return m["month"]
    # 退化：用 title 里的 "7月"/"8月" 猜测
    t = (macro.get("event") or {}).get("title") or ""
    import re
    mm = re.search(r"(\d+)月", t)
    if mm:
        return f"2026-{int(mm.group(1)):02d}"
    return ""


def infer_covered(macro: dict) -> set:
    """已覆盖事件集合（"kind:month"）：macro.json 的 covered 列表 + 当前 event 标题推断。"""
    cov = set(macro.get("covered") or [])
    t = (macro.get("event") or {}).get("title") or ""
    for rel, kind, month, name in CALENDAR:
        if name and name in t:
            cov.add(f"{kind}:{month}")
    return cov


_SERIES_CACHE: dict = {}


def cached_series(series_id: str) -> list:
    if series_id not in _SERIES_CACHE:
        _SERIES_CACHE[series_id] = get_series(series_id)
    return _SERIES_CACHE[series_id]


def has_data(kind: str, month: str) -> bool:
    """FRED 是否已有该事件目标月数据（没到点的发布会生成空值，挡住）。"""
    try:
        if kind == "cpi":
            return not math.isnan(mom_yoy(cached_series("CPIAUCSL"), month)["value"])
        if kind == "pce":
            return not math.isnan(mom_yoy(cached_series("PCEPI"), month)["value"])
        if kind == "ppi":
            return not math.isnan(mom_yoy(cached_series("PPIFIS"), month)["value"])
        if kind == "nonfarm":
            return month in {d for d, v in cached_series("PAYEMS")}
    except Exception:
        return False
    return False


def decide_event(macro: dict, today: str) -> tuple | None:
    """已到期、未覆盖（按 kind:month 粒度）、且 FRED 已有数据的事件；多个取发布日最新者。
    发布超过 10 天的陈旧事件不回补（防止覆盖更新的事件）。
    fomc 永远留给人工；ecb 仅在 ECB_DECISIONS 有决议记录时生成。"""
    from datetime import date as _date
    cov = infer_covered(macro)
    due = []
    for rel, kind, month, name in CALENDAR:
        if kind == "fomc" or f"{kind}:{month}" in cov:
            continue
        if kind == "ecb" and rel not in ECB_DECISIONS:
            continue
        if rel <= today and (_date.fromisoformat(today) - _date.fromisoformat(rel)).days <= 10:
            due.append((rel, kind, month, name))
    for ev in sorted(due, reverse=True):  # 发布日新的优先，避免回补陈旧事件
        if ev[1] == "ecb" or has_data(ev[1], ev[2]):
            return ev
    return None


def fetch_fred_daily(series_id: str) -> list[tuple[str, float]]:
    """日度序列：返回 [(YYYY-MM-DD, value)]，升序，跳过缺失值。"""
    url = FRED.format(id=series_id)
    req = Request(url, headers={"User-Agent": "macro-auto/1.0"})
    text = _urlopen_retry(req, timeout=25)
    rows: list[tuple[str, float]] = []
    for line in text.strip().splitlines()[1:]:
        if not line or "," not in line:
            continue
        d, v = line.split(",", 1)
        try:
            rows.append((d, float(v)))
        except ValueError:
            continue
    return rows


def build_ecb(macro: dict, rel: str, month: str, name: str) -> dict:
    dec = ECB_DECISIONS[rel]
    chg = dec["change_bp"]
    if chg > 0:
        stance, act = "偏鹰", f"加息{chg}bp"
    elif chg < 0:
        stance, act = "偏鸽", f"降息{-chg}bp"
    else:
        stance, act = "中性", "维持利率不变"
    conclusion = (
        f"（自动化快报·人工补录决议）欧洲央行{name.replace('欧洲央行', '')}：{act}，"
        f"存款便利利率/主要再融资/边际贷款 → {dec['deposit']:.2f}%/{dec['mro']:.2f}%/{dec['mlf']:.2f}%"
        f"（{dec['effective']} 起生效）。{dec.get('note', '')}"
        f"对有色与贵金属：欧央行紧缩→欧元走强压制美元指数，间接利多美元计价金属；"
        f"但全球同步收紧抬高实际利率，商品估值端承压。声明措辞细节以官方为准。"
    )
    return {
        "updated_at": today_iso(),
        "event": {
            "title": f"{name}落地快报（自动）",
            "released_at": today_iso(),
            "stance": stance,
            "conclusion": conclusion,
            "metrics": [
                {"name": "决议", "actual": act, "consensus": "—", "previous": "—", "month": month},
                {"name": "存款便利利率", "actual": f"{dec['deposit']:.2f}%", "consensus": "—", "previous": f"{dec['deposit'] - chg / 100:.2f}%"},
                {"name": "主要再融资利率", "actual": f"{dec['mro']:.2f}%", "consensus": "—", "previous": f"{dec['mro'] - chg / 100:.2f}%"},
                {"name": "边际贷款利率", "actual": f"{dec['mlf']:.2f}%", "consensus": "—", "previous": f"{dec['mlf'] - chg / 100:.2f}%"},
            ],
            "transmission": [
                {"asset": "欧央行", "view": stance, "detail": dec.get("note", "")},
                {"asset": "欧元 / 美元", "view": "欧强美弱", "detail": "欧美利差收窄→欧元走强→美元指数承压。"},
                {"asset": "美元 / 黄金", "view": "间接受益", "detail": "美元走弱利多金银；但实际利率全球上行是反向压制。"},
                {"asset": "有色", "view": "汇率端利多", "detail": "美元计价金属获汇率支撑，关注欧美紧缩差。"},
            ],
            "next": next_events(rel),
            "sources": [{"name": "ECB 官网决议声明", "url": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"}],
            "verification": "决议结果人工补录进 ECB_DECISIONS；声明措辞/发布会要点需人工精修。",
        },
    }


def check_ust_breakout(macro: dict, today: str) -> tuple[list, dict] | None:
    """美债四期限 60 日破位检查。返回 (破位明细, 全部期限水平) 或 None。
    当前快报发布不足 UST_MIN_EVENT_AGE_H 小时不抢版。"""
    upd = (macro.get("updated_at") or "")[:19]
    try:
        age_h = (datetime.now() - datetime.fromisoformat(upd)).total_seconds() / 3600
        if age_h < UST_MIN_EVENT_AGE_H:
            return None
    except Exception:
        pass  # 解析失败视为足够旧
    cov = infer_covered(macro)
    breaks = []
    levels = {}
    for tenor, sid in UST_SERIES.items():
        try:
            rows = fetch_fred_daily(sid)
        except Exception:
            continue
        if len(rows) < UST_LOOKBACK + 2:
            continue
        latest_d, latest_v = rows[-1]
        prev_v = rows[-2][1]
        window = [v for _, v in rows[-(UST_LOOKBACK + 1):-1]]
        hi, lo = max(window), min(window)
        levels[tenor] = {"date": latest_d, "value": latest_v, "chg_bp": round((latest_v - prev_v) * 100, 1),
                         "hi60": hi, "lo60": lo}
        ym = latest_d[:7]
        if latest_v > hi and f"ust:{sid}:up:{ym}" not in cov:
            breaks.append({"tenor": tenor, "sid": sid, "dir": "up", "date": latest_d,
                           "value": latest_v, "ref": hi, "key": f"ust:{sid}:up:{ym}"})
        elif latest_v < lo and f"ust:{sid}:down:{ym}" not in cov:
            breaks.append({"tenor": tenor, "sid": sid, "dir": "down", "date": latest_d,
                           "value": latest_v, "ref": lo, "key": f"ust:{sid}:down:{ym}"})
    if not breaks:
        return None
    return breaks, levels


def build_ust(breaks: list, levels: dict) -> dict:
    up = any(b["dir"] == "up" for b in breaks)
    stance = "偏鹰" if up else "偏鸽"
    seg = "；".join(
        f"{b['tenor']} {b['value']:.2f}% {'上破' if b['dir'] == 'up' else '下破'}60日{'新高' if b['dir'] == 'up' else '新低'}"
        f"（前{'高' if b['dir'] == 'up' else '低'} {b['ref']:.2f}%，{b['date']}）"
        for b in breaks
    )
    if up:
        fed = "收益率破位上行=政策预期/期限溢价重定价偏鹰，高利率维持时间拉长"
        gold = "通胀预期平稳下名义收益率破位≈实际利率上行→金银承压，美元偏强；若由财政供给/期限溢价驱动，避险盘或部分对冲"
    else:
        fed = "收益率破位下行=加息紧迫性消退/降息预期升温"
        gold = "名义收益率破位下行+美元走弱→实际利率下行，金银完整利多，银弹性更大"
    conclusion = (
        f"（自动化快报·FRED日度）美债收益率破位：{seg}。{fed}。"
        f"对贵金属：{gold}。对有色：利率端压力通过美元与贴现率传导，关注实际利率净方向。"
    )
    metrics = []
    for tenor in UST_SERIES:
        lv = levels.get(tenor)
        if lv:
            metrics.append({"name": f"美债{tenor}", "actual": f"{lv['value']:.2f}%",
                            "consensus": f"60日区间 {lv['lo60']:.2f}-{lv['hi60']:.2f}%",
                            "previous": f"日变动 {lv['chg_bp']:+.1f}bp"})
    return {
        "updated_at": today_iso(),
        "event": {
            "title": "美债收益率破位快报（自动）",
            "released_at": today_iso(),
            "stance": stance,
            "conclusion": conclusion,
            "metrics": metrics,
            "transmission": [
                {"asset": "美联储", "view": stance, "detail": fed},
                {"asset": "美债", "view": "破位", "detail": seg},
                {"asset": "美元 / 黄金", "view": stance, "detail": gold},
                {"asset": "有色", "view": "跟随", "detail": "美元与风险偏好联动，实际利率净方向定强弱。"},
            ],
            "next": next_events(date.today().isoformat()),
            "sources": [{"name": "FRED (DGS2/DGS5/DGS10/DGS30)", "url": "https://fred.stlouisfed.org/series/DGS10"}],
            "verification": "FRED 日度官方数据，破位=最新收盘突破前60个交易日高/低点；每期限每方向每月只报一次。",
        },
    }


def stance_from(cpi_core_yoy: float) -> str:
    if math.isnan(cpi_core_yoy):
        return "中性"
    if cpi_core_yoy >= 3.0:
        return "中性偏鹰"
    if cpi_core_yoy >= 2.0:
        return "中性"
    return "中性略鸽"


def build_cpi(macro: dict, rel: str, month: str, name: str) -> dict:
    cpi = get_series("CPIAUCSL")
    core = get_series("CPILFESL")
    h = mom_yoy(cpi, month)
    c = mom_yoy(core, month)
    stance = stance_from(c["yoy"])
    core_note = "核心通胀黏性仍高" if (c["yoy"] and c["yoy"] >= 3) else "核心温和回落"
    fed = "加息紧迫性进一步下降、9月按兵不动概率高" if (h["mom"] and h["mom"] <= 0.15) else "加息紧迫性未消、政策相机抉择"
    gold = "实际利率若随名义收益率下行+美元走弱则利多金银" if stance != "中性偏鹰" else "加息担忧压制金银、实际利率方向未明"
    conclusion = (
        f"（自动化快报·FRED实际值）{month} CPI环比{pct(h['mom'])}（前值{pct(round((h['prev']/prev_of(cpi, month)-1)*100,2))}）、"
        f"同比{pct(h['yoy'])}；核心环比{pct(c['mom'])}、核心同比{pct(c['yoy'])}。总量低位、{core_note}；"
        f"→{fed}，降息门槛仍高。对贵金属：{gold}；央行购金长期买盘维持偏多底色。"
    )
    next_evs = next_events(rel)
    return {
        "updated_at": today_iso(),
        "event": {
            "title": f"{name}落地快报（自动）",
            "released_at": today_iso(),
            "stance": stance,
            "conclusion": conclusion,
            "metrics": [
                {"name": "CPI 环比", "actual": pct(h["mom"]), "consensus": "—（自动化无共识）", "previous": "前月", "month": month},
                {"name": "CPI 同比", "actual": pct(h["yoy"]), "consensus": "—", "previous": "前年同月"},
                {"name": "核心CPI 环比", "actual": pct(c["mom"]), "consensus": "—", "previous": "前月"},
                {"name": "核心CPI 同比", "actual": pct(c["yoy"]), "consensus": "—", "previous": "前年同月"},
            ],
            "transmission": [
                {"asset": "美联储", "view": stance, "detail": fed},
                {"asset": "美债", "view": "名义收益率方向未明", "detail": "数据落地后看长端定价与实际利率。"},
                {"asset": "美元 / 黄金", "view": "实际利率驱动", "detail": gold},
                {"asset": "有色", "view": "跟随风险偏好", "detail": "宏观情绪主导，关注美元与风险资产联动。"},
            ],
            "next": next_evs,
            "sources": [{"name": "FRED (CPIAUCSL/CPILFESL)", "url": "https://fred.stlouisfed.org/series/CPIAUCSL"}],
            "verification": "数据来自 FRED 官方，自动化生成（无共识对比，环比对比前值）；如需人工精修可覆盖。",
        },
    }


def build_pce(macro: dict, rel: str, month: str, name: str) -> dict:
    pce = get_series("PCEPI")
    core = get_series("PCEPILFE")
    h = mom_yoy(pce, month)
    c = mom_yoy(core, month)
    stance = stance_from(c["yoy"])
    fed = "PCE延续回落→加息紧迫性下降" if (h["yoy"] and h["yoy"] <= 3.5) else "PCE偏高→政策谨慎"
    conclusion = (
        f"（自动化快报·FRED实际值）{month} PCE环比{pct(h['mom'])}、同比{pct(h['yoy'])}；"
        f"核心PCE环比{pct(c['mom'])}、同比{pct(c['yoy'])}。{fed}；降息门槛仍高，相机抉择。"
        f"贵金属看实际利率+美元：同步下行才构成完整利多。"
    )
    return {
        "updated_at": today_iso(),
        "event": {
            "title": f"{name}落地快报（自动）",
            "released_at": today_iso(),
            "stance": stance,
            "conclusion": conclusion,
            "metrics": [
                {"name": "PCE 环比", "actual": pct(h["mom"]), "consensus": "—", "previous": "前月", "month": month},
                {"name": "PCE 同比", "actual": pct(h["yoy"]), "consensus": "—", "previous": "前年同月"},
                {"name": "核心PCE 环比", "actual": pct(c["mom"]), "consensus": "—", "previous": "前月"},
                {"name": "核心PCE 同比", "actual": pct(c["yoy"]), "consensus": "—", "previous": "前年同月"},
            ],
            "transmission": [
                {"asset": "美联储", "view": stance, "detail": fed},
                {"asset": "美债", "view": "长端看实际利率", "detail": "PCE是Fed最看重指标，落地后看收益率反应。"},
                {"asset": "美元 / 黄金", "view": "实际利率驱动", "detail": "实际利率+美元同步下行→黄金完整利多。"},
                {"asset": "有色", "view": "跟随", "detail": "宏观情绪主导。"},
            ],
            "next": next_events(rel),
            "sources": [{"name": "FRED (PCEPI/PCEPILFE)", "url": "https://fred.stlouisfed.org/series/PCEPI"}],
            "verification": "数据来自 FRED 官方，自动化生成（无共识对比）；如需人工精修可覆盖。",
        },
    }


def build_nonfarm(macro: dict, rel: str, month: str, name: str) -> dict:
    pay = get_series("PAYEMS")
    unr = get_series("UNRATE")
    idx = {d: v for d, v in pay}
    current = idx.get(month, math.nan)
    prev = idx.get(prev_month(month), math.nan)
    add = round((current - prev) / 1000, 1) if not math.isnan(current) and not math.isnan(prev) else math.nan
    un_idx = {d: v for d, v in unr}
    un = un_idx.get(month, math.nan)
    fed = "就业降温→加息紧迫性下降、9月按兵不动概率升" if (not math.isnan(add) and add <= 50) else "就业有韧性→政策谨慎"
    stance = "中性略鸽" if (not math.isnan(add) and add <= 50) else "中性"
    conclusion = (
        f"（自动化快报·FRED实际值）{month} 非农新增{add if not math.isnan(add) else '—'}万人"
        f"（前值{round((prev/1000),1) if not math.isnan(prev) else '—'}万）、失业率{un if not math.isnan(un) else '—'}%。"
        f"{fed}。对贵金属：就业走弱+实际利率预期下行偏多金，银弹性大；留意月底PCE二次确认。"
    )
    return {
        "updated_at": today_iso(),
        "event": {
            "title": f"{name}落地快报（自动）",
            "released_at": today_iso(),
            "stance": stance,
            "conclusion": conclusion,
            "metrics": [
                {"name": "非农新增(万)", "actual": f"{add:.1f}" if not math.isnan(add) else "—", "consensus": "—", "previous": f"{round(prev/1000,1)}" if not math.isnan(prev) else "—", "month": month},
                {"name": "失业率", "actual": f"{un:.1f}" if not math.isnan(un) else "—", "consensus": "—", "previous": "前月"},
                {"name": "非农YoY趋势", "actual": "—", "consensus": "—", "previous": "自动"},
            ],
            "transmission": [
                {"asset": "美联储", "view": stance, "detail": fed},
                {"asset": "美债", "view": "就业弱利多长端", "detail": "就业降温→加息概率降→长端收益率或回落。"},
                {"asset": "美元 / 黄金", "view": "偏多黄金", "detail": "实际利率预期下行+美元走弱→黄金利多，银弹性大。"},
                {"asset": "有色", "view": "跟随", "detail": "宏观情绪主导。"},
            ],
            "next": next_events(rel),
            "sources": [{"name": "FRED (PAYEMS/UNRATE)", "url": "https://fred.stlouisfed.org/series/PAYEMS"}],
            "verification": "数据来自 FRED 官方，自动化生成（无共识对比）；如需人工精修可覆盖。",
        },
    }


def build_ppi(macro: dict, rel: str, month: str, name: str) -> dict:
    hd = cached_series("PPIFIS")        # 最终需求 PPI（官方口径）
    core = cached_series("WPSFD49116")  # 核心：最终需求除食品/能源/贸易
    h = mom_yoy(hd, month)
    c = mom_yoy(core, month)
    stance = stance_from(c["yoy"])
    fed = (
        "PPI同比高位、生产端通胀压力未消→加息/高利率维持时间拉长，政策偏鹰"
        if (h["yoy"] and h["yoy"] >= 4)
        else "PPI温和→加息紧迫性下降，政策相机抉择"
    )
    gold = (
        "生产端通胀高企→名义利率易上难下，若实际利率跟随上行则金银短线承压；"
        "但若市场解读为滞胀（通胀高+就业弱），黄金偏多、银弱腿"
        if stance == "中性偏鹰"
        else "实际利率若随名义收益率下行+美元走弱则利多金银"
    )
    conclusion = (
        f"（自动化快报·FRED实际值）{month} PPI(最终需求)环比{pct(h['mom'])}、同比{pct(h['yoy'])}；"
        f"核心PPI环比{pct(c['mom'])}、同比{pct(c['yoy'])}。{fed}。"
        f"对贵金属：{gold}；对有色：生产端通胀高企压制估值，但也印证上游成本支撑。"
    )
    return {
        "updated_at": today_iso(),
        "event": {
            "title": f"{name}落地快报（自动）",
            "released_at": today_iso(),
            "stance": stance,
            "conclusion": conclusion,
            "metrics": [
                {"name": "PPI 环比", "actual": pct(h["mom"]), "consensus": "—（自动化无共识）", "previous": "前月", "month": month},
                {"name": "PPI 同比", "actual": pct(h["yoy"]), "consensus": "—", "previous": "前年同月"},
                {"name": "核心PPI 环比", "actual": pct(c["mom"]), "consensus": "—", "previous": "前月"},
                {"name": "核心PPI 同比", "actual": pct(c["yoy"]), "consensus": "—", "previous": "前年同月"},
            ],
            "transmission": [
                {"asset": "美联储", "view": stance, "detail": fed},
                {"asset": "美债", "view": "名义收益率易上难下", "detail": "PPI是CPI领先指标，生产端通胀高企支撑长端收益率。"},
                {"asset": "美元 / 黄金", "view": stance, "detail": gold},
                {"asset": "有色", "view": "双向", "detail": "通胀高企压制估值 vs 上游成本支撑价格，看美元与实际利率净方向。"},
            ],
            "next": next_events(rel),
            "sources": [{"name": "FRED (PPIFIS/WPSFD49116)", "url": "https://fred.stlouisfed.org/series/PPIFIS"}],
            "verification": "数据来自 FRED 官方，自动化生成（无共识对比，环比对比前值）；如需人工精修可覆盖。",
        },
    }


def prev_of(rows, month):
    idx = {d: v for d, v in rows}
    return idx.get(prev_month(month), math.nan)


def prev_month(month: str) -> str:
    y, m = month.split("-")
    return f"{y}-{int(m)-1:02d}" if int(m) > 1 else f"{int(y)-1}-12"


def next_events(rel: str) -> list[dict]:
    out = []
    for r, kind, month, name in CALENDAR:
        if r > rel:
            out.append({"time": r, "event": name + ("（需人工核对）" if kind in ("fomc", "ecb") else "（自动）"), "watch": ""})
        if len(out) >= 4:
            break
    return out


def today_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S+08:00")


# ============ FOMC 情景决策树（条件格自动着色） ============
SCENARIO = {
    "title": "9月FOMC的情景分析：核心CPI与油价若一同走弱，则9月FOMC可顺理成章的鸽",
    "cpi_month": "2026-08",      # 核心CPI目标数据月
    "cpi_label": "今晚的8月CPI",
    "fomc_rel": "2026-09-15",    # FOMC决议日
}
SCENARIO_JSON = ROOT / "data" / "fomc_scenario.json"

# FOMC 决议人工补录（决议后填）：{"2026-09-15": {"hiked": True/False, "dots": "none"/"one_more", "note": "..."}}
FOMC_DECISIONS: dict = {}


def sina_brent() -> tuple[float | None, str]:
    """新浪布伦特实时价；失败回退 FRED DCOILBRENTEU 日度。"""
    try:
        req = Request("https://hq.sinajs.cn/list=hf_OIL",
                      headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "macro-auto/1.0"})
        import time
        raw = None
        for i in range(3):
            try:
                with urlopen(req, timeout=15) as r:
                    raw = r.read()
                break
            except Exception:
                time.sleep(2 * (i + 1))
        t = raw.decode("ascii", "ignore")  # 只取首字段数字，避开 GBK 编码
        v = float(t.split('="', 1)[1].split(",", 1)[0])
        if v > 0:
            return v, "新浪·布伦特实时"
    except Exception:
        pass
    try:
        rows = fetch_fred_daily("DCOILBRENTEU")
        return rows[-1][1], f"FRED 日度（{rows[-1][0]}）"
    except Exception:
        return None, ""


def build_scenario() -> None:
    """每次跑批都刷新情景树（不依赖宏观快报是否更新）。"""
    # 格1：核心CPI环比
    c = mom_yoy(cached_series("CPILFESL"), SCENARIO["cpi_month"])
    cpi_val = None if math.isnan(c["mom"]) else round(c["mom"], 1)
    if cpi_val is None:
        cpi_state = None
    elif cpi_val <= 0.1:
        cpi_state = 0
    elif cpi_val <= 0.2:
        cpi_state = 1
    else:
        cpi_state = 2
    # 格2：布油
    oil, oil_src = sina_brent()
    oil_state = None if oil is None else (0 if oil <= 90 else (1 if oil < 100 else 2))
    # 格3/4：FOMC 决议与点阵图（人工补录）
    dec = FOMC_DECISIONS.get(SCENARIO["fomc_rel"])
    fomc_state = None if not dec else (1 if dec.get("hiked") else 0)
    dots_state = None if not dec else (0 if dec.get("dots") == "none" else 1)
    # 综合判定
    if cpi_state == 0 and oil_state == 0:
        verdict = "鸽派通道打开：核心CPI与油价同弱 → 9月可不加息、点阵图或撤掉年内再加一次"
    elif cpi_state == 2 or oil_state == 2:
        verdict = "鹰派路径主导：通胀或油价未走弱 → 9月加息+点阵图保留年内再一次为基准"
    elif cpi_state is None and oil_state is None:
        verdict = "条件待定：等核心CPI落地与油价方向"
    else:
        verdict = "条件分裂：鸽鹰信号各半，9月决议看当天声明措辞，点阵图倾向保守"
    doc = {
        "updated_at": today_iso(),
        "title": SCENARIO["title"],
        "verdict": verdict,
        "decision_note": (dec or {}).get("note", ""),
        "columns": [
            {"head": SCENARIO["cpi_label"],
             "cells": ["核心CPI≤0.1%", "核心CPI≈0.2%", "核心CPI≥0.3%"],
             "state": cpi_state,
             "actual": None if cpi_val is None else f"实际 {cpi_val:+.1f}%（{SCENARIO['cpi_month']}）"},
            {"head": "下周初的油价",
             "cells": ["布油≤90", "布油≈95", "布油≥100"],
             "state": oil_state,
             "actual": None if oil is None else f"布油现价 {oil:.1f}（{oil_src}）"},
            {"head": "9月FOMC决议",
             "cells": ["不加息", "加息"],
             "state": fomc_state,
             "actual": None if fomc_state is None else ("已落地" if dec else None)},
            {"head": "9月FOMC点阵图",
             "cells": ["年内不再加息", "年内再1次加息"],
             "state": dots_state,
             "actual": None},
        ],
    }
    SCENARIO_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[scenario] 已刷新 {SCENARIO_JSON.relative_to(ROOT)} | CPI={cpi_val} 布油={oil} | {verdict[:30]}")


def main() -> int:
    force = "--force" in sys.argv
    macro = read_macro()
    today = date.today().isoformat()
    ev = decide_event(macro, today)
    if ev:
        rel, kind, month, name = ev
        builders = {"cpi": build_cpi, "pce": build_pce, "ppi": build_ppi, "nonfarm": build_nonfarm, "ecb": build_ecb}
        new = builders[kind](macro, rel, month, name)
        new["covered"] = sorted(infer_covered(macro) | {f"{kind}:{month}"})
    else:
        ust = check_ust_breakout(macro, today)
        if not ust and not force:
            print("[macro] 无新到期事件，跳过")
            try:
                build_scenario()
            except Exception as e:
                print(f"[scenario] 失败（不影响主流程）: {e}")
            return 0
        if ust:
            breaks, levels = ust
            new = build_ust(breaks, levels)
            new["covered"] = sorted(infer_covered(macro) | {b["key"] for b in breaks})
        else:
            rel, kind, month, name = ("2026-08-28", "pce", "2026-07", "测试PCE")
            new = build_pce(macro, rel, month, name)
            new["covered"] = sorted(infer_covered(macro) | {f"{kind}:{month}"})
    MACRO.parent.mkdir(parents=True, exist_ok=True)
    MACRO.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[macro] 已生成 {new['event']['title']} → data/macro.json")
    try:
        build_scenario()
    except Exception as e:
        print(f"[scenario] 失败（不影响主流程）: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
