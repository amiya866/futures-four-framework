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
框架：总量 vs 核心、环比边际、同比趋势 → Fed路径(加息紧迫性/降息门槛) → 金银传导(实际利率)。
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


def fetch_fred(series_id: str) -> list[tuple[str, float]]:
    """返回 [(YYYY-MM, value)]，升序。"""
    url = FRED.format(id=series_id)
    req = Request(url, headers={"User-Agent": "macro-auto/1.0"})
    with urlopen(req, timeout=20) as r:
        text = r.read().decode("utf-8")
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
    发布超过 10 天的陈旧事件不回补（防止覆盖更新的事件）。"""
    from datetime import date as _date
    cov = infer_covered(macro)
    due = []
    for rel, kind, month, name in CALENDAR:
        if kind == "fomc" or f"{kind}:{month}" in cov:
            continue
        if rel <= today and (_date.fromisoformat(today) - _date.fromisoformat(rel)).days <= 10:
            due.append((rel, kind, month, name))
    for ev in sorted(due, reverse=True):  # 发布日新的优先，避免回补陈旧事件
        if has_data(ev[1], ev[2]):
            return ev
    return None


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
            out.append({"time": r, "event": name + ("（自动）" if kind != "fomc" else "（需人工核对）"), "watch": ""})
        if len(out) >= 4:
            break
    return out


def today_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def main() -> int:
    force = "--force" in sys.argv
    macro = read_macro()
    today = date.today().isoformat()
    ev = decide_event(macro, today)
    if not ev and not force:
        print("[macro] 无新到期事件，跳过")
        return 0
    rel, kind, month, name = ev if ev else ("2026-08-28", "pce", "2026-07", "测试PCE")
    builders = {"cpi": build_cpi, "pce": build_pce, "ppi": build_ppi, "nonfarm": build_nonfarm}
    new = builders[kind](macro, rel, month, name)
    new["covered"] = sorted(infer_covered(macro) | {f"{kind}:{month}"})
    MACRO.parent.mkdir(parents=True, exist_ok=True)
    MACRO.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[macro] 已生成 {new['event']['title']} → data/macro.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
