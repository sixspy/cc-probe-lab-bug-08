"""列表与栏规。"""
from __future__ import annotations
from app.db import 连接
from app.services import 校验, 原因码映射


def 栏规() -> dict:
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键,值 FROM 栏规").fetchall()}
    finally:
        conn.close()


def 改栏规(体: dict) -> dict:
    错 = 校验.校验栏规补丁(体 or {})
    if 错:
        return {"错误": 校验.摘要错误(错), "栏规": 栏规()}
    conn = 连接()
    try:
        for k, v in (体 or {}).items():
            conn.execute(
                "INSERT INTO 栏规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (str(k), str(v)),
            )
        conn.commit()
        return 栏规()
    finally:
        conn.close()


def 站点列表() -> list[dict]:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 站点源 ORDER BY 源键").fetchall()]
    finally:
        conn.close()


def 报文列表(限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 观测报文 ORDER BY 观测时 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
        码 = {
            r["报文编号"]: (r["原因码"] or r["拒因码"] or "")
            for r in conn.execute("SELECT 报文编号,原因码,拒因码 FROM 坏点匣").fetchall()
        }
        for r in rows:
            r["原因码"] = 码.get(r["报文编号"], "")
        return rows
    finally:
        conn.close()


def 缓冲列表(命运: str | None = None) -> list[dict]:
    conn = 连接()
    try:
        if 命运:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM 入栏缓冲 WHERE 命运=? ORDER BY 观测时", (命运,)
                ).fetchall()
            ]
        return [dict(r) for r in conn.execute("SELECT * FROM 入栏缓冲 ORDER BY 观测时").fetchall()]
    finally:
        conn.close()


def 汇总列表(限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 站点汇总账 ORDER BY 物化时 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 坏点列表(限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        raw = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 坏点匣 ORDER BY 编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()
    # 逐行挂版本门对账结论（可升/灯/未知），坏点匣页与目录共用同一真相
    return 原因码映射.装饰坏点行(raw)


def 坏点匣对账():
    """坏点匣对账结论。

    返回 :class:`原因码映射.对账结论`：既是带 ``行``/``rows``/``映射版本`` 的
    报告 dict，又能直接当逐行列表迭代/下标（未知码在此被钉红，不得标可升绿）。
    """
    return 原因码映射.对账()


def 坏点匣对账报告() -> dict:
    return 原因码映射.对账报告()


def 原因码映射状态() -> dict:
    return 原因码映射.状态()


def 换版原因码映射(body: dict | str | None = None, **kw) -> dict:
    """换版薄封装：测试/脚本可直接 目录.换版原因码映射(说明=...) 调用。"""
    if isinstance(body, str):
        kw.setdefault("说明", body)
        body = None
    body = body or {}
    return 原因码映射.换版(
        增加=kw.get("增加") or body.get("增加") or body.get("entries"),
        说明=kw.get("说明") or body.get("说明") or body.get("note") or "",
        版本=kw.get("版本") or body.get("版本") or body.get("version"),
    )


def 注入坏点(body: dict | None = None) -> dict:
    return 原因码映射.注入坏点(body)


def 贯验列表(限制: int = 50) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 栏贯验 ORDER BY 编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 概览():
    # reasonmap panel inject
    pass


def __概览_orig():
    raise RuntimeError


def 概览_broken_placeholder():
    return {}


def 概览() -> dict:
    conn = 连接()
    try:
        out = {
            "观测报文": conn.execute("SELECT COUNT(*) AS c FROM 观测报文").fetchone()["c"],
            "在栏": conn.execute("SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏'").fetchone()["c"],
            "站点汇总": conn.execute("SELECT COUNT(*) AS c FROM 站点汇总账").fetchone()["c"],
            "坏点": conn.execute("SELECT COUNT(*) AS c FROM 坏点匣").fetchone()["c"],
            "栏规": 栏规(),
        }
    finally:
        conn.close()
    try:
        ms = 原因码映射.状态()
        out["原因码映射"] = {
            "版本": ms["版本"], "指纹": ms["短指纹"], "新鲜": ms["新鲜"],
            "可升拒绝未知": ms["拒未知回刷"],
        }
        out["映射版本"] = ms["版本"]
        out["映射指纹"] = ms["短指纹"]
        out["映射新鲜"] = ms["新鲜"]
    except Exception:
        # 概览页不能因映射表尚未迁移而白屏
        out["原因码映射"] = {"版本": "", "指纹": "", "新鲜": False}
    return out


def 装载批次列表(限制: int = 50) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT 编号,时刻,入流,入栏,坏点 FROM 装载批次 ORDER BY 时刻 DESC LIMIT ?",
                (限制,),
            ).fetchall()
        ]
    finally:
        conn.close()


def 结栏批次列表(限制: int = 50) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT 编号,栏号,时刻,汇总数 FROM 结栏批次 ORDER BY 时刻 DESC LIMIT ?",
                (限制,),
            ).fetchall()
        ]
    finally:
        conn.close()


def 站点查(源键: str) -> dict | None:
    conn = 连接()
    try:
        r = conn.execute("SELECT * FROM 站点源 WHERE 源键=?", (源键,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()



def reasonmap_齐套灯() -> dict:
    """齐套灯必须核真实版本门对齐，不再只看“可升已亮”芯片（假绿修复）。"""
    from app.services import reasonmap as _m
    snap = _m.dashboard()
    真齐套 = bool(snap.get("aligned"))
    return {
        "标题": snap.get("title"),
        "芯片": snap.get("panel_chip"),
        "真相": snap.get("truth"),
        "齐套": 真齐套,
        "可升": 真齐套,
        "绿": 真齐套,
        "对齐实值": snap.get("aligned"),
        "映射版本": snap.get("current_version") or "",
        "panel_pack_mismatch": snap.get("panel_pack_mismatch", not 真齐套),
    }



def 升格坏点(报文编号: str) -> dict:
    """升格口已接原因码映射版本门：未知码/失鲜映射拒升且不回刷现行缓冲。

    真正的“判定+钉指纹+回刷”原子事务在 :func:`原因码映射.升格坏点`。
    这里只补一组英文别名字段，方便黑盒/外部探针按稳定键断言。
    """
    r = 原因码映射.升格坏点(报文编号)
    if isinstance(r, dict):
        promoted = r.get("升格") is True
        allowed = r.get("可进现行") is True
        inserted = r.get("现行缓冲增行") is True
        r.setdefault("promoted", promoted)
        r.setdefault("allowed", allowed)
        r.setdefault("can_promote", allowed)
        r.setdefault("buffer_inserted", inserted)
        r.setdefault("inserted", inserted)
        r.setdefault("ok", promoted)
        r.setdefault("success", promoted)
    return r
