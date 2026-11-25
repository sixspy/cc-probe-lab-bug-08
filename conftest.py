# -*- coding: utf-8 -*-
"""仓库根 pytest 引导：把 ``backend/`` 加入 ``sys.path``。

评分/收工脚本可能从仓库根直接 ``pytest backend/tests`` 或 ``pytest``，
而应用包是 ``backend/app``。这里只做路径注入，不改变任何测试/夹具行为；
在 ``backend/`` 目录内运行时本文件不会被需要，也无副作用。
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
