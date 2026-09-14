# -*- coding: utf-8 -*-
"""从知识星球分类面板数据生成渊行「星球研报速递」数据。
源：金属总网 小作文平台\\知识星球\\panel\\data\\zsxq_panel.json 的 categories.研报纪要（最新 30 条）。
输出：data/zsxq_research.json
用法：python scripts/build_zsxq_research.py [--panel PANEL_JSON]
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = Path(r"D:\Kimi\金属总网\网站构建\小作文平台\知识星球\panel\data\zsxq_panel.json")
OUT = ROOT / "data" / "zsxq_research.json"
PANEL_URL = "https://amiya866.github.io/metals-framework/zsxq-panel/#研报纪要"
KEEP = 30
COMM2SYM = {"cu": "CU", "al": "AL", "pb": "PB", "zn": "ZN",
            "ni": "NI", "sn": "SN", "li": "LC", "si": "SI"}


def main() -> None:
    panel = PANEL
    if "--panel" in sys.argv:
        panel = Path(sys.argv[sys.argv.index("--panel") + 1])
    d = json.loads(panel.read_text(encoding="utf-8"))
    items = (d.get("categories") or {}).get("研报纪要") or []
    seen, dedup = set(), []
    for x in sorted(items, key=lambda x: x.get("date", ""), reverse=True):
        key = x.get("url") or (x.get("date", "") + (x.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(x)
    items = dedup[:KEEP]
    out_items = []
    for x in items:
        pts = [p for p in (x.get("points") or []) if p and not p.startswith("#")]
        summary = "；".join(pts) if pts else (x.get("full") or x.get("summary") or "")
        summary = summary.strip()
        if len(summary) > 160:
            summary = summary[:160].rstrip() + "…"
        tag = "/".join(COMM2SYM[c] for c in (x.get("comms") or []) if c in COMM2SYM)
        out_items.append({
            "date": x.get("date", ""),
            "sector": "研报纪要",
            "tag": tag,
            "title": (x.get("title") or "").strip(),
            "summary": summary,
            "source": x.get("source") or "知识星球·前沿信息收录",
            "url": x.get("url") or "",
            "files": x.get("files") or [],
        })
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    OUT.write_text(json.dumps({
        "updated_at": now,
        "source": d.get("source", ""),
        "source_url": PANEL_URL,
        "category": "研报纪要",
        "items": out_items,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"zsxq_research.json: {len(out_items)} 条, 最新 {out_items[0]['date'] if out_items else '—'}")


if __name__ == "__main__":
    main()
