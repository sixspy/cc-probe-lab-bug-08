#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原因码映射版本门 · 换版/升格争用脚本（失败测的可执行压测版）。

场景：一边对一个“任何映射版本都不认识”的原因码坏点点“一键升格”，
一边并发给原因码映射换版（轮换版本指纹，但绝不加入该未知码）。

合格判据（任一不满足即 exit 1）：
1. 该未知报文在现行 ``/api/入栏缓冲`` 中始终 0 行；
2. 没有任何一次升格回执为成功；
3. 事后对账把该点标红 ``可升=false``，且版本门新鲜（凭证指纹一致）。

用法：
    python3 scripts/reasonmap_race.py --base-url http://127.0.0.1:8320
    BASE_URL=http://127.0.0.1:8100 python3 scripts/reasonmap_race.py --rounds 40

纯标准库实现，便于在容器外/评分机直接运行。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid


def _request(base: str, method: str, path: str, payload: dict | None = None, timeout: float = 30):
    # 中文路由需百分号编码；保留 URL 结构字符
    path = urllib.parse.quote(path, safe="/?=&%:+")
    url = base.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"错误": raw}
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            # 服务端写锁串行时偶发连接重置/忙，退避重试（不影响最终判据）
            last = e
            time.sleep(0.2 * (attempt + 1))
    raise RuntimeError(f"请求失败 {method} {path}: {last!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8320"))
    ap.add_argument("--promoters", type=int, default=4)
    ap.add_argument("--cutoverers", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=20, help="每个线程的操作轮数")
    args = ap.parse_args()

    base = args.base_url
    stamp = uuid.uuid4().hex[:8]
    bh = f"RACE-SCRIPT-{stamp}"
    code = f"RC_RACE_SCRIPT_NEVER_{stamp.upper()}"

    print(f"[race] base={base} 未知报文={bh} 未知码={code}")

    status, ver = _request(base, "GET", "/api/原因码映射")
    if status != 200 or not ver.get("版本"):
        print(f"[race][FAIL] 读不到原因码映射版本门：{status} {ver}")
        return 2
    print(f"[race] 当前映射 {ver.get('版本')}@{str(ver.get('短指纹'))} 新鲜={ver.get('新鲜')}")

    status, inj = _request(base, "POST", "/api/坏点匣/注入",
                           {"报文编号": bh, "原因码": code, "未知": True})
    if status != 200 or not inj.get("写入"):
        print(f"[race][FAIL] 注入未知码坏点失败：{status} {inj}")
        return 2
    print("[race] 已注入未知码坏点；开始并发升格 × 换版 …")

    start = threading.Event()
    outcomes: list[dict] = []
    errors: list[str] = []
    lock = threading.Lock()

    def promote_worker() -> None:
        start.wait(10)
        for _ in range(args.rounds):
            try:
                _, r = _request(base, "POST", "/api/坏点匣/升格", {"报文编号": bh})
                with lock:
                    outcomes.append(r if isinstance(r, dict) else {"raw": r})
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(f"promote: {e!r}")

    def cutover_worker() -> None:
        start.wait(10)
        for _ in range(args.rounds):
            try:
                # 关键：换版说明里声明不得加入该未知码；默认换版只轮换版本/指纹
                _, r = _request(base, "POST", "/api/原因码映射/换版",
                                {"说明": f"race {stamp}，不加入 {code}"})
                if not (isinstance(r, dict) and r.get("版本")):
                    with lock:
                        errors.append(f"cutover bad resp: {r}")
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(f"cutover: {e!r}")

    threads = [threading.Thread(target=promote_worker) for _ in range(args.promoters)]
    threads += [threading.Thread(target=cutover_worker) for _ in range(args.cutoverers)]
    t0 = time.time()
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(timeout=120)
        if t.is_alive():
            print("[race][FAIL] 工作线程超时（疑似死锁）")
            return 3
    dt = time.time() - t0

    if errors:
        print(f"[race][FAIL] 并发请求出现错误（{len(errors)}）：")
        for e in errors[:10]:
            print("   ", e)
        return 4

    success = [r for r in outcomes if r.get("升格") is True or r.get("可进现行") is True]
    _, buf = _request(base, "GET", "/api/入栏缓冲")
    buf_rows = buf if isinstance(buf, list) else buf.get("rows", [])
    leaked = [r for r in buf_rows if str(r.get("报文编号")) == bh]

    _, rep = _request(base, "GET", "/api/坏点匣/对账")
    row = next((r for r in rep.get("行", []) if r.get("报文编号") == bh), None)

    print(f"[race] 完成：升格尝试 {len(outcomes)}，成功 {len(success)}，"
          f"现行缓冲泄漏 {len(leaked)} 行，用时 {dt:.1f}s")
    if row:
        print(f"[race] 对账：可升={row.get('可升')} 灯={row.get('灯')} 未知={row.get('未知')} "
              f"映射={row.get('映射版本')}")
    print(f"[race] 版本门：{rep.get('映射版本')} 新鲜={rep.get('新鲜')}")

    if leaked:
        print("[race][RED] 未知码在换版/升格并发窗口漏拦，进入现行缓冲！")
        return 1
    if success:
        print(f"[race][RED] 存在未知码升格成功回执：{success[:3]}")
        return 1
    if row is None or row.get("可升") is not False or row.get("灯") != "红":
        print(f"[race][RED] 对账未把未知码标红禁升：{row}")
        return 1
    if rep.get("新鲜") is not True:
        print(f"[race][RED] 换版后凭证与当前指纹不一致：{rep.get('映射版本')} fresh={rep.get('新鲜')}")
        return 1

    print("[race][GREEN] 未知码零漏拦，对账红，版本凭证一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
