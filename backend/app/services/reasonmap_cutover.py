"""原因码映射切流账册（工程形态 A）：旁路凭证表钉映射版本指纹。

修复后不再是“只记软笔记 + 亮假灯”的空壳：append_cutover 会真实执行映射换版，
由 app.services.原因码映射 在同一张旁路凭证表（映射凭证）上改钉新指纹，
并把 reasonmap_* 展示键同步为诚实的对齐值。
"""
from __future__ import annotations

from app.db import 连接
from app.services import reasonmap as core

_SLUG = "reasonmap"
_TITLE = "原因码映射"
_OK = "可升已亮"


def append_cutover(ref_id: int, note: str = "") -> dict:
    from app.services import 原因码映射 as R
    st = R.换版(说明=f"ref_id={ref_id} {note or _TITLE}".strip())
    conn = 连接()
    try:
        core._ensure(conn)
        core._set(conn, f"{_SLUG}_cutover_note_{ref_id}", note or _TITLE)
        conn.commit()
    finally:
        conn.close()
    dash = core.dashboard()
    return {
        "ref_id": ref_id,
        "note": note,
        "panel": core.panel_chip(),
        "truth": core.truth_flag(),
        "active_read": core.active_read_ref(),
        "cutover_fp": st["指纹"],
        "版本": st["版本"],
        "reject_refresh": True,
        "aligned": st["新鲜"],
        "panel_pack_mismatch": not st["新鲜"],
    }


def board() -> dict:
    from app.services import 原因码映射 as R
    st = R.状态()
    dash = core.dashboard()
    dash.update({
        "fate": "cutover_book",
        "selected_form": "A_sidecar_credential",
        "版本": st["版本"],
        "current_version": st["版本"],
        "canonical_fp": st["指纹"],
        "pinned_fp": st["钉住指纹"],
        "fresh": st["新鲜"],
        "reject_unknown_writeback": True,
        "panel_pack_mismatch": not st["新鲜"],
        "aligned": st["新鲜"],
    })
    dash["fate"] = "cutover_book"
    return dash
