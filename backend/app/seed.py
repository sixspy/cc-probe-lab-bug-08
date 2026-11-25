from datetime import datetime, timezone
from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 栏规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 站点源 (
  源键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL,
  介质 TEXT NOT NULL DEFAULT '大气',
  区域 TEXT NOT NULL DEFAULT '',
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 观测报文 (
  报文编号 TEXT PRIMARY KEY,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已装载',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 入栏缓冲 (
  报文编号 TEXT PRIMARY KEY,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  栏号 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '在栏',
  入栏时 TEXT NOT NULL,
  原因码 TEXT NOT NULL DEFAULT '',
  映射版本 TEXT NOT NULL DEFAULT '',
  映射指纹 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 站点汇总账 (
  汇总编号 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL,
  报文数 INTEGER NOT NULL,
  均值 REAL NOT NULL,
  物化时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已汇总'
);
CREATE TABLE IF NOT EXISTS 坏点匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  报文编号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  指标键 TEXT NOT NULL DEFAULT 'PM25',
  原因 TEXT NOT NULL,
  原因码 TEXT NOT NULL DEFAULT '',
  拒因码 TEXT NOT NULL DEFAULT '',
  读数 REAL NOT NULL,
  观测时 TEXT NOT NULL,
  入匣时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 栏贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  在栏笔数 INTEGER NOT NULL,
  汇总报文数 INTEGER NOT NULL,
  坏点笔数 INTEGER NOT NULL,
  是否对齐 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  入流 INTEGER NOT NULL DEFAULT 0,
  入栏 INTEGER NOT NULL DEFAULT 0,
  坏点 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 探栏元 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 结栏批次 (
  编号 TEXT PRIMARY KEY,
  栏号 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  汇总数 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _迁移旧库(conn)
    # 原因码映射版本门：种子 v1(过期)/v2(当前) + 旁路凭证钉指纹，并同步诚实面板键
    from app.services import 原因码映射
    原因码映射.初始化映射(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 栏规").fetchone()["c"] == 0:
        for k, v in {
            "当前栏号": "B-demo",
            "PM25上限": "75",
            "PM25下限": "0",
            "标定偏移上限": "5",
            "栏策略": "按站点指标汇总均值",
        }.items():
            conn.execute("INSERT INTO 栏规(键,值) VALUES (?,?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 站点源").fetchone()["c"] == 0:
        for row in [
            ("站-河东", "河东大气站", "大气", "城区", "示范站"),
            ("站-湖西", "湖西水质站", "水质", "湖区", "示范站"),
            ("站-北岭", "北岭大气站", "大气", "近郊", "示范站"),
            ("站-江口", "江口大气站", "大气", "河口", "示范站"),
            ("站-林场", "林场微站", "大气", "林区", "示范站"),
        ]:
            conn.execute(
                "INSERT INTO 站点源(源键,名称,介质,区域,说明) VALUES (?,?,?,?,?)",
                row,
            )
    conn.commit()
    conn.close()



def _现有列(conn, 表: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({表})").fetchall()}


def _加列若缺(conn, 表: str, 列: str, 声明: str) -> None:
    if 列 not in _现有列(conn, 表):
        conn.execute(f"ALTER TABLE {表} ADD COLUMN {列} {声明}")


def _迁移旧库(conn) -> None:
    """已部署卷里的旧表没有原因码/版本指纹列，幂等补列并回填旧原因文本。"""
    _加列若缺(conn, "坏点匣", "指标键", "TEXT NOT NULL DEFAULT 'PM25'")
    _加列若缺(conn, "坏点匣", "原因码", "TEXT NOT NULL DEFAULT ''")
    _加列若缺(conn, "坏点匣", "拒因码", "TEXT NOT NULL DEFAULT ''")
    _加列若缺(conn, "入栏缓冲", "原因码", "TEXT NOT NULL DEFAULT ''")
    _加列若缺(conn, "入栏缓冲", "映射版本", "TEXT NOT NULL DEFAULT ''")
    _加列若缺(conn, "入栏缓冲", "映射指纹", "TEXT NOT NULL DEFAULT ''")
    # 旧坏点行只有中文原因：按文案回填最早两版就认识的原因码
    conn.execute(
        "UPDATE 坏点匣 SET 原因码='RC_PM25_OUT_OF_RANGE' "
        "WHERE COALESCE(原因码,'')='' AND 原因 LIKE '%越界%'"
    )
    conn.execute(
        "UPDATE 坏点匣 SET 原因码='RC_RULE_THRESHOLD_CORRUPT' "
        "WHERE COALESCE(原因码,'')='' AND 原因 LIKE '%阈值损坏%'"
    )
    conn.execute(
        "UPDATE 坏点匣 SET 拒因码=原因码 WHERE COALESCE(拒因码,'')='' AND 原因码<>''"
    )
    conn.commit()
