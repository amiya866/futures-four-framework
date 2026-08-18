#!/usr/bin/env python3
"""校验研究注册表(build_fundamentals.py 的 FOCUS/CONTRADICTIONS/SURVEY_NOTES/CHART_PICK)的一致性。
CI 门禁: 任何一项不一致即失败, 防止矛盾文案/指标绑定漂移。"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "scripts" / "build_fundamentals.py").read_text(encoding="utf-8")

tree = ast.parse(SRC)
dicts = {}
for node in ast.walk(tree):
    target = None
    if isinstance(node, ast.AnnAssign):
        target = getattr(node.target, "id", "")
    elif isinstance(node, ast.Assign):
        target = getattr(node.targets[0], "id", "")
    if target in {"FOCUS", "CONTRADICTIONS", "SURVEY_NOTES", "CHART_PICK"}:
        dicts[target] = ast.literal_eval(node.value)

focus, contra, survey, chart_pick = dicts["FOCUS"], dicts["CONTRADICTIONS"], dicts["SURVEY_NOTES"], dicts["CHART_PICK"]

# FOCUS 结构完整: route/contradiction/metrics 三要素 + 指标五元组
for sym, cfg in focus.items():
    assert cfg.get("contradiction"), f"{sym} 缺 contradiction"
    assert 2 <= len(cfg.get("metrics") or []) <= 3, f"{sym} 指标数 {len(cfg.get('metrics') or [])} 不在 2-3"
    for m in cfg["metrics"]:
        assert len(m) == 5 and all(m), f"{sym} 指标五元组不完整: {m}"
    assert all(v for v in cfg.get("marginal_focus", "").split("|") if v.strip()), f"{sym} marginal_focus 有空项"

# CHART_PICK 必须指向该品种的指标之一
for sym, mid in chart_pick.items():
    assert sym in focus, f"CHART_PICK {sym} 不在 FOCUS"
    ids = {m[0] for m in focus[sym]["metrics"]}
    assert mid in ids, f"CHART_PICK {sym} 的 {mid} 不在其指标列表"

# SURVEY_NOTES 必须是已知品种
known = set(focus) | set(contra)
for sym in survey:
    assert sym in known, f"SURVEY_NOTES 未知品种 {sym}"

print(f"research registry OK: FOCUS={len(focus)} CONTRADICTIONS={len(contra)} SURVEY={len(survey)} CHART_PICK={len(chart_pick)}")
