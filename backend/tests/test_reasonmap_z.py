# -*- coding: utf-8 -*-
"""争用失败测：映射换版与升格并发时不得漏拦未知码。

TOCTOU 风险：升格口若在事务外读映射、或先判定后钉指纹，换版并发下
就可能按旧判定把未知码回刷进现行缓冲。这里多线程同时“升格 + 换版”，
硬断言该未知报文在现行缓冲始终 0 行，且每次升格回执都不是成功。

换版只轮换映射版本/指纹，绝不把该未知码加进映射，因此它在任何版本下
都是未知码。
"""
from __future__ import annotations

import threading
import uuid

from app.db import 连接
from app.seed import 此刻
from app.services import 目录

报文号 = "RM-Z-RACE-0001"
未知码 = "RC_Z_RACE_NEVER_MAPPED_08"


def _确保原因码列() -> None:
    conn = 连接()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(坏点匣)").fetchall()]
        if "原因码" not in cols:
            conn.execute("ALTER TABLE 坏点匣 ADD COLUMN 原因码 TEXT NOT NULL DEFAULT ''")
            conn.commit()
    finally:
        conn.close()


def _准备() -> None:
    _确保原因码列()
    conn = 连接()
    try:
        conn.execute(
            """INSERT INTO 坏点匣(报文编号,站点键,原因,原因码,读数,观测时,入匣时)
               VALUES (?,?,?,?,?,?,?)""",
            (报文号, "站-北岭", "争用注入未知码", 未知码, 888.0,
             "2026-11-25T03:00:00Z", 此刻()),
        )
        conn.commit()
    finally:
        conn.close()


def _缓冲行数() -> int:
    conn = 连接()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 报文编号=?", (报文号,)
        ).fetchone()["c"]
    finally:
        conn.close()


def _原始换版_模拟() -> None:
    """修复前没有真换版口：直接搅动元表指纹，模拟“映射瞬间换版”。"""
    conn = 连接()
    try:
        fp = f"race-{uuid.uuid4().hex}"
        conn.execute(
            "INSERT INTO 探栏元(键,值) VALUES('reasonmap_cutover_fp',?) "
            "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
            (fp,),
        )
        conn.commit()
    finally:
        conn.close()


def test_z_换版与升格并发_未知码零漏拦():
    _准备()
    assert _缓冲行数() == 0

    真换版 = getattr(目录, "换版原因码映射", None)
    结果集: list[dict] = []
    错误集: list[BaseException] = []
    锁 = threading.Lock()
    开始 = threading.Event()

    def 升格工(轮数: int) -> None:
        try:
            开始.wait(timeout=10)
            for _ in range(轮数):
                r = 目录.升格坏点(报文号)
                with 锁:
                    结果集.append(r if isinstance(r, dict) else {"raw": r})
        except BaseException as e:  # noqa: BLE001 - 争用测试要回收线程异常
            with 锁:
                错误集.append(e)

    def 换版工(轮数: int) -> None:
        try:
            开始.wait(timeout=10)
            for _ in range(轮数):
                if callable(真换版):
                    真换版(说明="争用测试换版，不加入 RC_Z_RACE_NEVER_MAPPED_08")
                else:
                    _原始换版_模拟()
        except BaseException as e:  # noqa: BLE001
            with 锁:
                错误集.append(e)

    线程 = [
        threading.Thread(target=升格工, args=(12,)),
        threading.Thread(target=升格工, args=(12,)),
        threading.Thread(target=升格工, args=(12,)),
        threading.Thread(target=换版工, args=(15,)),
        threading.Thread(target=换版工, args=(15,)),
    ]
    for t in 线程:
        t.start()
    开始.set()
    for t in 线程:
        t.join(timeout=60)
        assert not t.is_alive(), "争用线程超时未结束（疑似死锁）"

    assert not 错误集, f"并发过程抛错：{错误集!r}"

    # 核心争用不变量：任何瞬间都不得漏拦进现行
    assert _缓冲行数() == 0, "换版/升格并发窗口漏拦：未知码进入现行缓冲"
    成功 = [r for r in 结果集 if r.get("升格") is True or r.get("可进现行") is True]
    assert not 成功, f"存在未知码升格成功回执：{成功[:3]}"

    # 事后凭证一致：侧车钉住的指纹必须等于当前版指纹，映射新鲜
    if callable(真换版):
        状态 = 目录.原因码映射状态()
        assert 状态.get("新鲜") is True, f"换版后凭证失鲜：{状态}"
        assert 状态.get("钉住指纹") == 状态.get("指纹")
