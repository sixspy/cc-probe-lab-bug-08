# -*- coding: utf-8 -*-
"""失败测乙：坏点匣对账不得把未知原因码标成“可升绿”。

假绿分属坏点匣与目录：只亮“可升已亮”芯片、只改原因文案都不算修。
对账必须按“当前钉住的原因码映射版本”逐行给结论：
映射内码才可亮绿“可升”；未知码只能红“禁升/未知桶”。
"""
from __future__ import annotations

from app.db import 连接
from app.seed import 此刻
from app.services import 目录

未知号 = "RM-Y-UNK-GREEN"
已知号 = "RM-Y-KNOWN-GREEN"
未知码 = "RC_Y_UNKNOWN_08"
已知码 = "RC_PM25_OUT_OF_RANGE"


def _确保原因码列() -> None:
    conn = 连接()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(坏点匣)").fetchall()]
        if "原因码" not in cols:
            conn.execute("ALTER TABLE 坏点匣 ADD COLUMN 原因码 TEXT NOT NULL DEFAULT ''")
            conn.commit()
    finally:
        conn.close()


def _写(编号: str, 码: str) -> None:
    _确保原因码列()
    conn = 连接()
    try:
        conn.execute(
            """INSERT INTO 坏点匣(报文编号,站点键,原因,原因码,读数,观测时,入匣时)
               VALUES (?,?,?,?,?,?,?)""",
            (编号, "站-河东", "对账测试", 码, 200.0, "2026-11-25T02:00:00Z", 此刻()),
        )
        conn.commit()
    finally:
        conn.close()


def _取行(报告, 编号: str) -> dict:
    if isinstance(报告, dict):
        行集 = 报告.get("行") or 报告.get("rows") or []
    else:
        行集 = 报告
    by = {r["报文编号"]: r for r in 行集}
    assert 编号 in by, f"对账缺少 {编号}"
    return by[编号]


def test_y1_对账函数存在且不把未知码标可升():
    assert callable(getattr(目录, "坏点匣对账", None)), (
        "目录.坏点匣对账 未实现：当前未知码会被目录/芯片标成可升绿"
    )
    _写(未知号, 未知码)
    报告 = 目录.坏点匣对账()
    row = _取行(报告, 未知号)

    assert row.get("可升") is False, "未知码被对账标成可升"
    # 各种可能的“绿色”表达都不允许为真
    assert row.get("可升格") is False
    assert row.get("promotable") is False
    assert row.get("绿") is False
    assert row.get("green") is False
    assert row.get("未知") is True or row.get("unknown") is True
    灯 = str(row.get("灯", "")) + str(row.get("色调", "")) + str(row.get("tone", ""))
    assert "绿" not in 灯 and "ok" not in 灯.lower() and "好" not in 灯, f"未知码亮了绿灯：{row}"


def test_y2_坏点列表本身也不得带假绿():
    """目录.坏点列表 是坏点匣页数据源，逐行结论必须与对账一致。"""
    _写("RM-Y-LIST-UNK", "RC_Y_LIST_UNKNOWN_08")
    rows = {r["报文编号"]: r for r in 目录.坏点列表()}
    assert "RM-Y-LIST-UNK" in rows
    r = rows["RM-Y-LIST-UNK"]
    assert r.get("可升") is False, f"坏点列表给未知码标了可升：{r}"
    assert r.get("绿") is not True


def test_y3_已知码对照为绿_未知为红():
    _写(未知号 + "2", 未知码 + "2")
    _写(已知号, 已知码)
    报告 = 目录.坏点匣对账()
    u = _取行(报告, 未知号 + "2")
    k = _取行(报告, 已知号)
    assert u.get("可升") is False
    assert k.get("可升") is True, f"映射内已知码应可升：{k}"
    assert k.get("绿") is True


def test_y4_对账报告带映射版本指纹():
    assert callable(getattr(目录, "坏点匣对账报告", None))
    rep = 目录.坏点匣对账报告()
    assert rep.get("映射版本") or rep.get("版本")
    fp = rep.get("指纹") or rep.get("映射指纹")
    assert fp and fp not in ("stale-fp",), "对账报告未钉真实映射指纹"
