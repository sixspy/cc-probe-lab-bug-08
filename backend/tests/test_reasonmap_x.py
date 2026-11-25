# -*- coding: utf-8 -*-
"""失败测甲：未知原因码“一键升格”后，现行缓冲不得增行。

题面硬约束：未知码不得升正式；不做版本门则脏点进缓冲。
本测试直接钉住真实升格口 ``app.services.目录.升格坏点`` 与现行缓冲表，
并附带 HTTP 一键升格路由，防止“只改原因文案”的半修假绿。
"""
from __future__ import annotations

import asyncio

from app.db import 连接
from app.seed import 此刻
from app.services import 目录

未知码 = "RC_X_UNKNOWN_FUTURE_08"
报文号 = "RM-X-未知码-0001"


def _确保原因码列() -> None:
    """兼容旧库：旧坏点匣没有原因码列时先补上，以便复现“写入未知原因码”。"""
    conn = 连接()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(坏点匣)").fetchall()]
        if "原因码" not in cols:
            conn.execute("ALTER TABLE 坏点匣 ADD COLUMN 原因码 TEXT NOT NULL DEFAULT ''")
            conn.commit()
    finally:
        conn.close()


def _写入坏点(报文编号: str, 原因码: str) -> None:
    _确保原因码列()
    conn = 连接()
    try:
        conn.execute(
            """INSERT INTO 坏点匣(报文编号,站点键,原因,原因码,读数,观测时,入匣时)
               VALUES (?,?,?,?,?,?,?)""",
            (报文编号, "站-河东", "新拒因码（映射表过期，落未知桶）", 原因码,
             999.0, "2026-11-25T01:00:00Z", 此刻()),
        )
        conn.commit()
    finally:
        conn.close()


def _现行缓冲行数(报文编号: str) -> int:
    conn = 连接()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 报文编号=?", (报文编号,)
        ).fetchone()["c"]
    finally:
        conn.close()


def test_x1_服务口_未知码升格不进现行缓冲():
    _写入坏点(报文号, 未知码)
    assert _现行缓冲行数(报文号) == 0

    回 = 目录.升格坏点(报文号)

    # 硬断言：现行缓冲不得为未知码增行
    assert _现行缓冲行数(报文号) == 0, "未知原因码被放进现行缓冲——脏点入栏"
    # 回执必须可区分：明确拒绝、不可进现行
    assert isinstance(回, dict)
    assert 回.get("升格") is not True
    assert 回.get("可进现行") is False
    assert 回.get("现行缓冲增行") is False
    assert str(回.get("结果", "")) .startswith("拒升") or "未知" in str(回.get("错误", "")) + str(回.get("结果", ""))


def test_x2_http一键升格_未知码不进现行():
    _写入坏点("RM-X-HTTP-0002", "RC_X_HTTP_UNKNOWN_08")

    async def _打一次():
        from app.main import app
        async with app.test_client() as c:
            resp = await c.post("/api/坏点匣/升格", json={"报文编号": "RM-X-HTTP-0002"})
            return resp.status_code, await resp.get_json()

    status, body = asyncio.run(_打一次())
    assert status == 200
    assert isinstance(body, dict)
    assert body.get("升格") is not True
    assert body.get("可进现行") is False
    assert _现行缓冲行数("RM-X-HTTP-0002") == 0


def test_x3_已知码可升格_证明门不是全拦():
    """对照：映射内已知码应当能正常升格，未知/已知必须可区分。"""
    _写入坏点("RM-X-KNOWN-0003", "RC_PM25_OUT_OF_RANGE")
    回 = 目录.升格坏点("RM-X-KNOWN-0003")
    assert isinstance(回, dict)
    assert 回.get("升格") is True, f"已知码应允许升格，实际：{回}"
    assert 回.get("可进现行") is True
    assert _现行缓冲行数("RM-X-KNOWN-0003") == 1
