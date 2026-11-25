# -*- coding: utf-8 -*-
"""原因码映射版本门（本题真正落点）。

工程形态 A：**旁路凭证表钉住映射版本指纹，并拒未知码升格回刷**。

不变量：
1. 只有当前映射版本内的原因码才允许把坏点回刷进现行 ``入栏缓冲``；
2. 旁路凭证表 ``映射凭证`` 单行钉住“当前版本 + 指纹”，指纹由映射条目规范化哈希得到，
   钉值、当前版本行、重算指纹三者一致才叫“映射新鲜”；
3. 升格的“判定 + 回刷”与映射换版都在 ``BEGIN IMMEDIATE`` 写事务内完成，
   SQLite 写锁把两类事务串行化，消除“先按旧映射判定、换版后回刷”的 TOCTOU 漏拦窗口；
4. 每次升格尝试都写 ``升格回刷`` 凭证账，未知码/失鲜一律 ``可进现行=0``，可区分、可审计。

旧的 ``app.services.reasonmap*`` 只是面板空壳；本模块是真实闸门，并把诚实状态单向同步
到 ``探栏元`` 的 reasonmap_* 展示键，供旧看板/页面读到对齐值。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid

from app import db
from app.db import 连接
from app.seed import 此刻

未知桶 = "未知桶"
形态 = "旁路凭证表钉指纹+原子版本门"

# 进程内把“换版 / 升格回刷”串行化，避免同进程线程在 SQLite 写锁上互相 BUSY；
# 跨进程/多 worker 的正确性仍由 BEGIN IMMEDIATE 写事务兜底。
门锁 = threading.Lock()

# 已对哪些库路径执行过建表 DDL（测试会按用例切换 db.库路径，故按路径缓存）
_已确保库: set[str] = set()

# v1：过期映射（只认识最早的门槛码）
_v1条目 = [
    ("RC_GATE_PASS", "过门槛", "通过"),
    ("RC_NON_CONTROLLED_PASS", "非受控指标默认过门槛", "通过"),
    ("RC_PM25_OUT_OF_RANGE", "PM25越界", "阈值越界"),
    ("RC_RULE_THRESHOLD_CORRUPT", "栏规阈值损坏", "规则损坏"),
]
# v2：补齐新拒因码（标定漂移），即“换版后”的新鲜映射
_v2新增 = [
    ("RC_CALIB_DRIFT", "标定偏移越限", "标定质控"),
]
当前种子版本 = "v2"
过期种子版本 = "v1"


# --------------------------------------------------------------------------- 建表/指纹

def 确保表(conn) -> None:
    """建表 DDL 只能在显式事务外调用：executescript 会隐式 COMMIT。

    按当前 db.库路径缓存，避免每次升格都跑一遍 DDL 加剧写锁争用。
    """
    key = str(db.库路径)
    if key in _已确保库:
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS 原因码映射版本 (
          版本 TEXT PRIMARY KEY,
          指纹 TEXT NOT NULL,
          时刻 TEXT NOT NULL,
          状态 TEXT NOT NULL,
          说明 TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS 原因码映射条目 (
          原因码 TEXT PRIMARY KEY,
          中文名 TEXT NOT NULL,
          桶 TEXT NOT NULL,
          引入版本 TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS 映射凭证 (
          编号 INTEGER PRIMARY KEY CHECK (编号 = 1),
          钉住版本 TEXT NOT NULL,
          钉住指纹 TEXT NOT NULL,
          签发时刻 TEXT NOT NULL,
          拒未知回刷 INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS 升格回刷 (
          编号 INTEGER PRIMARY KEY AUTOINCREMENT,
          时刻 TEXT NOT NULL,
          报文编号 TEXT NOT NULL,
          原因码 TEXT NOT NULL DEFAULT '',
          结果 TEXT NOT NULL,
          可进现行 INTEGER NOT NULL DEFAULT 0,
          钉住版本 TEXT NOT NULL DEFAULT '',
          钉住指纹 TEXT NOT NULL DEFAULT '',
          判定指纹 TEXT NOT NULL DEFAULT '',
          轨 TEXT NOT NULL DEFAULT '现行缓冲'
        );
        CREATE TABLE IF NOT EXISTS 探栏元 (
          键 TEXT PRIMARY KEY,
          值 TEXT NOT NULL
        );
        """
    )
    conn.commit()
    _已确保库.add(key)


def 计算指纹(版本: str, 条目) -> str:
    规范 = sorted((str(r[0]), str(r[1]), str(r[2])) for r in 条目)
    body = json.dumps(
        {"版本": 版本, "条目": 规范}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _元设置(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO 探栏元(键,值) VALUES (?,?) "
        "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
        (key, value),
    )


def 同步展示键(conn, 版本: str, 指纹: str, 新鲜: bool) -> None:
    """把真实版本门状态单向同步给旧 reasonmap 面板键（诚实灯，不再假绿）。"""
    ok = "可升已亮"
    bad = "未知码升格"
    _元设置(conn, "reasonmap_panel_chip", ok if 新鲜 else "映射失鲜")
    _元设置(conn, "reasonmap_truth", ok if 新鲜 else bad)
    _元设置(conn, "reasonmap_active_read", "cutover_book")
    _元设置(conn, "reasonmap_cutover_fp", 指纹 if 新鲜 else "stale-fp")
    _元设置(conn, "reasonmap_reject_refresh", "1")
    _元设置(conn, "reasonmap_mode", "sidecar_credential")
    _元设置(conn, "reasonmap_gate_bypass", "0" if 新鲜 else "1")
    _元设置(conn, "reasonmap_current_version", 版本)
    _元设置(conn, "reasonmap_live_flag", "")


# --------------------------------------------------------------------------- 种子

def 初始化映射(conn) -> None:
    """幂等种子：v1 标过期，v2 当前，旁路凭证钉 v2 真指纹。

    已初始化过（生产卷/换版后重启）则绝不回滚操作员的换版结果。
    """
    确保表(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 原因码映射版本").fetchone()["c"] > 0:
        st = _状态_locked(conn)
        if st["版本"] and st["钉住指纹"]:
            同步展示键(conn, st["版本"], st["指纹"], st["新鲜"])
        return

    t = 此刻()
    for code, name, bucket in _v1条目:
        conn.execute(
            "INSERT OR REPLACE INTO 原因码映射条目(原因码,中文名,桶,引入版本) VALUES (?,?,?,?)",
            (code, name, bucket, 过期种子版本),
        )
    fp1 = 计算指纹(过期种子版本, _v1条目)
    conn.execute(
        "INSERT INTO 原因码映射版本(版本,指纹,时刻,状态,说明) VALUES (?,?,?,?,?)",
        (过期种子版本, fp1, t, "过期", "初版原因码映射，缺少标定漂移等新拒因码"),
    )

    v2条目 = _v1条目 + _v2新增
    for code, name, bucket in _v2新增:
        conn.execute(
            "INSERT OR REPLACE INTO 原因码映射条目(原因码,中文名,桶,引入版本) VALUES (?,?,?,?)",
            (code, name, bucket, 当前种子版本),
        )
    fp2 = 计算指纹(当前种子版本, v2条目)
    conn.execute(
        "INSERT INTO 原因码映射版本(版本,指纹,时刻,状态,说明) VALUES (?,?,?,?,?)",
        (当前种子版本, fp2, t, "当前", "补齐新拒因码；旁路凭证表钉住本版指纹"),
    )
    conn.execute(
        "INSERT INTO 映射凭证(编号,钉住版本,钉住指纹,签发时刻,拒未知回刷) VALUES (1,?,?,?,1)",
        (当前种子版本, fp2, t),
    )
    同步展示键(conn, 当前种子版本, fp2, True)


# --------------------------------------------------------------------------- 状态

def _状态_locked(conn) -> dict:
    # 调用方须已 确保表 且持有连接/事务；此处不再 executescript，以免隐式提交事务。
    active = conn.execute(
        "SELECT * FROM 原因码映射版本 WHERE 状态='当前' ORDER BY 版本 DESC LIMIT 1"
    ).fetchone()
    pin = conn.execute("SELECT * FROM 映射凭证 WHERE 编号=1").fetchone()
    entries = [
        dict(r)
        for r in conn.execute(
            "SELECT 原因码,中文名,桶,引入版本 FROM 原因码映射条目 ORDER BY 原因码"
        ).fetchall()
    ]
    versions = [
        dict(r)
        for r in conn.execute(
            "SELECT 版本,指纹,时刻,状态,说明 FROM 原因码映射版本 ORDER BY 时刻, 版本"
        ).fetchall()
    ]

    ver = active["版本"] if active else ""
    active_fp = active["指纹"] if active else ""
    recomputed = 计算指纹(ver, [(e["原因码"], e["中文名"], e["桶"]) for e in entries]) if ver else ""
    pin_ver = pin["钉住版本"] if pin else ""
    pin_fp = pin["钉住指纹"] if pin else ""
    新鲜 = bool(
        ver and active_fp and pin_ver == ver and pin_fp == active_fp == recomputed
    )
    return {
        "标题": "原因码映射",
        "缺陷": "原因码映射过期",
        "形态": 形态,
        "版本": ver,
        "当前版本": ver,
        "映射版本": ver,
        "指纹": active_fp,
        "映射指纹": active_fp,
        "判定指纹": recomputed,
        "短指纹": active_fp[:12],
        "钉住版本": pin_ver,
        "钉住指纹": pin_fp,
        "钉住短指纹": pin_fp[:12],
        "新鲜": 新鲜,
        "映射新鲜": 新鲜,
        "aligned": 新鲜,
        "拒未知回刷": True,
        "reject_refresh": True,
        "active_read": "cutover_book",
        "未知桶": 未知桶,
        "条目": entries,
        "映射": {e["原因码"]: e for e in entries},
        "版本史": versions,
    }


def 状态() -> dict:
    conn = 连接()
    try:
        确保表(conn)
        return _状态_locked(conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------- 换版

def 换版(增加: list | None = None, 说明: str = "", 版本: str | None = None) -> dict:
    with 门锁:
        return _换版_事务(增加, 说明, 版本)


def _换版_事务(增加: list | None = None, 说明: str = "", 版本: str | None = None) -> dict:
    """原子换版：加入可选新码 → 算新指纹 → 切当前版 → 旁路凭证改钉新指纹。

    与 :func:`升格坏点` 一样取 ``BEGIN IMMEDIATE`` 写锁，二者全局串行。
    """
    conn = 连接()
    try:
        确保表(conn)
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        n = conn.execute("SELECT COUNT(*) AS c FROM 原因码映射版本").fetchone()["c"]
        new_ver = 版本 or f"v{n + 1}"
        t = 此刻()
        for item in 增加 or []:
            code = str(item.get("原因码") or item.get("code") or "").strip()
            if not code:
                continue
            conn.execute(
                "INSERT INTO 原因码映射条目(原因码,中文名,桶,引入版本) VALUES (?,?,?,?) "
                "ON CONFLICT(原因码) DO UPDATE SET 中文名=excluded.中文名, 桶=excluded.桶",
                (
                    code,
                    str(item.get("中文名") or item.get("名称") or code),
                    str(item.get("桶") or "默认桶"),
                    new_ver,
                ),
            )
        entries = conn.execute(
            "SELECT 原因码,中文名,桶 FROM 原因码映射条目"
        ).fetchall()
        fp = 计算指纹(new_ver, [(r["原因码"], r["中文名"], r["桶"]) for r in entries])

        conn.execute("UPDATE 原因码映射版本 SET 状态='过期' WHERE 状态='当前'")
        conn.execute(
            "INSERT INTO 原因码映射版本(版本,指纹,时刻,状态,说明) VALUES (?,?,?,?,?) "
            "ON CONFLICT(版本) DO UPDATE SET 指纹=excluded.指纹, 时刻=excluded.时刻, "
            "状态='当前', 说明=excluded.说明",
            (new_ver, fp, t, "当前", 说明 or f"映射换版 {new_ver}"),
        )
        conn.execute(
            "INSERT INTO 映射凭证(编号,钉住版本,钉住指纹,签发时刻,拒未知回刷) VALUES (1,?,?,?,1) "
            "ON CONFLICT(编号) DO UPDATE SET 钉住版本=excluded.钉住版本, "
            "钉住指纹=excluded.钉住指纹, 签发时刻=excluded.签发时刻",
            (new_ver, fp, t),
        )
        同步展示键(conn, new_ver, fp, True)
        conn.commit()
        return 状态()
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- 原因码解析

def 从原因文本推码(原因: str) -> str:
    s = str(原因 or "")
    if "越界" in s:
        return "RC_PM25_OUT_OF_RANGE"
    if "阈值损坏" in s:
        return "RC_RULE_THRESHOLD_CORRUPT"
    if "标定" in s and ("漂移" in s or "偏移" in s):
        return "RC_CALIB_DRIFT"
    return ""


def _行原因码(row: dict) -> str:
    code = str(row.get("原因码") or row.get("拒因码") or "").strip()
    if code:
        return code
    return 从原因文本推码(row.get("原因", ""))


# --------------------------------------------------------------------------- 原子升格门

def 升格坏点(报文编号: str) -> dict:
    with 门锁:
        return _升格坏点_事务(报文编号)


def _升格坏点_事务(报文编号: str) -> dict:
    """版本门升格口。未知码/映射失鲜一律拒升并写回刷凭证，绝不写现行缓冲。"""
    conn = 连接()
    try:
        确保表(conn)
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        st = _状态_locked(conn)
        ver, fp, pin_fp = st["版本"], st["指纹"], st["钉住指纹"]

        row = conn.execute(
            "SELECT * FROM 坏点匣 WHERE 报文编号=? ORDER BY 编号 DESC LIMIT 1",
            (报文编号,),
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return {"错误": "无此坏点", "升格": False, "可进现行": False,
                    "现行缓冲增行": False, "报文编号": 报文编号}
        r = dict(row)
        code = _行原因码(r)
        metric = r.get("指标键") or "PM25"
        t = 此刻()

        def 落账(结果: str, 可进: int, 判定fp: str) -> None:
            conn.execute(
                """INSERT INTO 升格回刷
                   (时刻,报文编号,原因码,结果,可进现行,钉住版本,钉住指纹,判定指纹,轨)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (t, 报文编号, code, 结果, 可进, ver, pin_fp, 判定fp, "现行缓冲"),
            )

        # 1) 映射新鲜度门：凭证钉值必须等于当前版指纹（且重算一致）
        if not st["新鲜"]:
            落账("拒升-映射失鲜", 0, st["判定指纹"])
            conn.commit()
            return {
                "升格": False, "成功": False, "可进现行": False, "现行缓冲增行": False,
                "结果": "拒升-映射失鲜",
                "错误": f"原因码映射版本门失鲜：凭证钉 {st['钉住版本']}@{pin_fp[:12]}，"
                        f"当前 {ver}@{fp[:12]}，禁止升格回刷",
                "报文编号": 报文编号, "原因码": code,
                "映射版本": ver, "映射指纹": fp, "钉住指纹": pin_fp,
            }

        # 2) 未知码门：必须在当前映射版本的码集内
        if not code or code not in st["映射"]:
            落账("拒升-未知码", 0, fp)
            conn.commit()
            return {
                "升格": False, "成功": False, "ok": False, "可进现行": False,
                "现行缓冲增行": False, "结果": "拒升-未知码",
                "错误": f"原因码 {code or '(空码)'} 不在映射版本 {ver} 内，"
                        f"落入{未知桶}，不得升正式/进现行缓冲",
                "报文编号": 报文编号, "原因码": code,
                "映射版本": ver, "映射指纹": fp, "钉住指纹": pin_fp,
                "桶": 未知桶,
            }

        # 旧行只有中文原因时，顺手把推出的码持久化
        if not (r.get("原因码") or ""):
            conn.execute("UPDATE 坏点匣 SET 原因码=? WHERE 编号=?", (code, r["编号"]))

        exists = conn.execute(
            "SELECT 1 FROM 入栏缓冲 WHERE 报文编号=?", (报文编号,)
        ).fetchone()
        if exists:
            落账("已在现行", 1, fp)
            conn.commit()
            return {
                "升格": True, "成功": True, "重复": True, "可进现行": True,
                "现行缓冲增行": False, "结果": "已在现行",
                "报文编号": 报文编号, "原因码": code,
                "映射版本": ver, "映射指纹": fp,
            }

        conn.execute(
            """INSERT INTO 入栏缓冲
               (报文编号,站点键,指标键,读数,观测时,栏号,命运,入栏时,原因码,映射版本,映射指纹)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (报文编号, r["站点键"], metric, r["读数"], r["观测时"],
             "B-demo", "在栏", t, code, ver, fp),
        )
        conn.execute("UPDATE 观测报文 SET 命运='已入栏' WHERE 报文编号=?", (报文编号,))
        落账("已升格入现行", 1, fp)
        conn.commit()
        return {
            "升格": True, "成功": True, "ok": True, "可进现行": True,
            "现行缓冲增行": True, "结果": "已升格入现行",
            "报文编号": 报文编号, "原因码": code, "指标键": metric,
            "映射版本": ver, "映射指纹": fp, "钉住指纹": pin_fp,
        }
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- 对账装饰

def 装饰坏点行(raw_rows: list[dict], st: dict | None = None) -> list[dict]:
    if st is None:
        st = 状态()
    conn = 连接()
    try:
        现行 = {
            r["报文编号"]
            for r in conn.execute("SELECT 报文编号 FROM 入栏缓冲").fetchall()
        }
    finally:
        conn.close()

    out: list[dict] = []
    for r0 in raw_rows:
        r = dict(r0)
        code = _行原因码(r)
        known = bool(code) and code in st["映射"]
        in_cur = r.get("报文编号") in 现行
        can = bool(known and st["新鲜"] and not in_cur)
        if in_cur:
            灯, 色调, green = "青", "ok", False
            拒因 = "已在现行缓冲"
        elif not st["新鲜"]:
            灯, 色调, green = "黄", "警", False
            拒因 = "映射版本失鲜，暂禁升格"
        elif not known:
            灯, 色调, green = "红", "危", False
            拒因 = f"未知原因码，落{未知桶}，禁升格"
        else:
            灯, 色调, green = "绿", "好", True
            拒因 = ""
        meta = st["映射"].get(code) or {}
        r.update({
            "原因码": code,
            "原因码中文名": meta.get("中文名", ""),
            "码桶": meta.get("桶", 未知桶 if not known else ""),
            "映射版本": st["版本"],
            "映射指纹": st["短指纹"],
            "映射指纹全": st["指纹"],
            "已知": known,
            "未知": not known,
            "unknown": not known,
            "is_unknown": not known,
            "可升": can,
            "可升格": can,
            "promotable": can,
            "can_promote": can,
            "allowed": can,
            "blocked": not can,
            "绿": can and green,
            "green": can and green,
            "灯": 灯,
            "色调": 色调,
            "tone": "ok" if 灯 == "绿" else ("danger" if 灯 == "红" else "warn"),
            "已在现行": in_cur,
            "in_buffer": in_cur,
            "拒因": 拒因,
            "reject_reason": 拒因,
            "reason": 拒因,
            "bucket": meta.get("桶", 未知桶 if not known else ""),
            "mapping_version": st["版本"],
            "mapping_fingerprint": st["指纹"],
        })
        out.append(r)
    return out


def 对账行() -> list[dict]:
    conn = 连接()
    try:
        raw = [dict(r) for r in conn.execute(
            "SELECT * FROM 坏点匣 ORDER BY 编号 DESC LIMIT 500"
        ).fetchall()]
    finally:
        conn.close()
    return 装饰坏点行(raw)


class 对账结论(dict):
    """兼形容器：既是完整报告 dict（``r["行"]`` / ``r["映射版本"]``），
    又能直接当“行列表”迭代、``len()``、整数下标/切片。

    这样无论调用方把 ``目录.坏点匣对账()`` 当报告还是当行集，契约都成立。
    JSON 序列化时按 dict 输出全部报告键（含 ``行``/``rows``）。
    """

    def __init__(self, report: dict):
        super().__init__(report)

    @property
    def _行集(self) -> list[dict]:
        return dict.__getitem__(self, "行")

    def __iter__(self):
        return iter(self._行集)

    def __len__(self) -> int:
        return len(self._行集)

    def __bool__(self) -> bool:
        return bool(self._行集)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._行集[key]
        return dict.__getitem__(self, key)


def 对账() -> "对账结论":
    """完整对账结论（dict 报告 + list 行集双兼容）。"""
    return 对账结论(对账报告())


def 对账报告() -> dict:
    st = 状态()
    rows = 对账行()
    return {
        "时刻": 此刻(),
        "标题": "坏点匣对账",
        "映射版本": st["版本"],
        "版本": st["版本"],
        "version": st["版本"],
        "指纹": st["指纹"],
        "映射指纹": st["指纹"],
        "短指纹": st["短指纹"],
        "fresh": st["新鲜"],
        "新鲜": st["新鲜"],
        "映射新鲜": st["新鲜"],
        "形态": st["形态"],
        "行": rows,
        "rows": rows,
        "items": rows,
        "总数": len(rows),
        "total": len(rows),
        "可升数": sum(1 for r in rows if r["可升"]),
        "promotable_count": sum(1 for r in rows if r["可升"]),
        "未知数": sum(1 for r in rows if r["未知"]),
        "unknown_count": sum(1 for r in rows if r["未知"]),
        "已在现行数": sum(1 for r in rows if r["已在现行"]),
        "红灯数": sum(1 for r in rows if r["灯"] == "红"),
        "red_count": sum(1 for r in rows if r["灯"] == "红"),
    }


# --------------------------------------------------------------------------- 注入复现

def 注入坏点(body: dict | None = None) -> dict:
    """写入一个带（可未知）原因码的坏点，供“写入未知码再点升格”复现/黑盒验证。"""
    body = body or {}
    code = str(body.get("原因码") or body.get("拒因码") or "").strip()
    if not code or body.get("未知"):
        code = code or f"RC_NEW_{uuid.uuid4().hex[:10].upper()}"
    bh = str(body.get("报文编号") or f"RM-INJECT-{uuid.uuid4().hex[:8]}")
    site = str(body.get("站点键") or "站-河东")
    metric = str(body.get("指标键") or "PM25")
    读数 = float(body.get("读数", 999.0))
    t = 此刻()
    conn = 连接()
    try:
        确保表(conn)
        conn.execute(
            """INSERT INTO 坏点匣(报文编号,站点键,指标键,原因,原因码,拒因码,读数,观测时,入匣时)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (bh, site, metric,
             str(body.get("原因") or f"注入原因码 {code}"),
             code, code, 读数,
             str(body.get("观测时") or "2026-11-25T04:00:00Z"), t),
        )
        conn.commit()
    finally:
        conn.close()
    row = next((r for r in 对账行() if r["报文编号"] == bh), None)
    return {"写入": True, "报文编号": bh, "原因码": code, "对账": row}


def 回刷账(限制: int = 100) -> list[dict]:
    conn = 连接()
    try:
        确保表(conn)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM 升格回刷 ORDER BY 编号 DESC LIMIT ?", (限制,)
        ).fetchall()]
    finally:
        conn.close()
