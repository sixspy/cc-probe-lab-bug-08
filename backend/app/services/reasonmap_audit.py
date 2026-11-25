"""原因码映射读轨审计。"""
from __future__ import annotations

from app.services import reasonmap as core
from app.services import reasonmap_cutover as cutover
from app.services import reasonmap_dualwrite as dual


def audit_summary() -> dict:
    return {
        "title": "原因码映射审计",
        "core": core.dashboard(),
        "cutover": cutover.board(),
        "dualwrite": dual.dual_board(),
        "half": core.half_fix_display(),
    }
