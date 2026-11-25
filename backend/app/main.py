from pathlib import Path
from quart import Quart, jsonify, request, send_from_directory, redirect
from app import seed
from app.services import 目录, 装载, 结栏, 贯验, 夹具, 统计, 说明
from app.services import reasonmap as reasonmap_svc
from app.services import reasonmap_cutover as reasonmap_cut_svc
from app.services import reasonmap_dualwrite as reasonmap_dual_svc
from app.services import reasonmap_audit as reasonmap_audit_svc

_STATIC = Path(__file__).resolve().parent / "static"
app = Quart(__name__)


@app.before_serving
async def _boot():
    seed.初始化库()


@app.get("/login")
async def login_page():
    return await send_from_directory(_STATIC, "login.html")


@app.get("/")
async def index():
    return await send_from_directory(_STATIC, "index.html")


@app.get("/api/概览")
async def api_概览():
    return jsonify(目录.概览())


@app.get("/api/仓情")
async def api_仓情():
    return jsonify(说明.仓情())


@app.get("/api/栏规")
async def api_栏规_get():
    return jsonify(目录.栏规())


@app.post("/api/栏规")
async def api_栏规_post():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(目录.改栏规(body))


@app.get("/api/站点源")
async def api_站点():
    return jsonify(目录.站点列表())


@app.get("/api/观测报文")
async def api_报文():
    return jsonify(目录.报文列表())


@app.get("/api/入栏缓冲")
async def api_缓冲():
    return jsonify(目录.缓冲列表())


@app.get("/api/站点汇总账")
async def api_汇总():
    return jsonify(目录.汇总列表())


@app.get("/api/坏点匣")
async def api_坏点():
    return jsonify(目录.坏点列表())


@app.get("/api/坏点匣/对账")
async def api_坏点对账():
    return jsonify(目录.坏点匣对账报告())


@app.get("/api/坏点匣对账")
async def api_坏点对账_别名():
    return jsonify(目录.坏点匣对账报告())


@app.post("/api/坏点匣/升格")
async def api_坏点升格():
    body = await request.get_json(force=True, silent=True) or {}
    编号 = body.get("报文编号") or body.get("id") or body.get("ref") or ""
    return jsonify(目录.升格坏点(str(编号)))


@app.post("/api/升格坏点")
async def api_升格坏点_别名():
    body = await request.get_json(force=True, silent=True) or {}
    编号 = body.get("报文编号") or body.get("id") or ""
    return jsonify(目录.升格坏点(str(编号)))


@app.post("/api/坏点匣/<path:ref>/升格")
async def api_坏点升格_路径(ref: str):
    return jsonify(目录.升格坏点(ref))


@app.post("/api/坏点匣/注入")
async def api_坏点注入():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(目录.注入坏点(body))


@app.post("/api/坏点匣/注入未知码")
async def api_坏点注入未知码():
    body = await request.get_json(force=True, silent=True) or {}
    body.setdefault("未知", True)
    return jsonify(目录.注入坏点(body))


@app.post("/api/原因码映射/注入未知码")
async def api_映射注入未知码():
    body = await request.get_json(force=True, silent=True) or {}
    body.setdefault("未知", True)
    return jsonify(目录.注入坏点(body))


@app.post("/api/坏点匣/一键升格")
async def api_坏点一键升格():
    body = await request.get_json(force=True, silent=True) or {}
    编号 = body.get("报文编号") or body.get("id") or body.get("ref") or ""
    return jsonify(目录.升格坏点(str(编号)))


@app.post("/api/坏点匣")
async def api_坏点登记():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(目录.注入坏点(body))


@app.get("/api/原因码映射")
async def api_原因码映射():
    return jsonify(目录.原因码映射状态())


@app.post("/api/原因码映射/换版")
async def api_原因码映射换版():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(目录.换版原因码映射(body))


@app.get("/api/升格回刷账")
async def api_升格回刷账():
    from app.services import 原因码映射 as _R
    return jsonify(_R.回刷账())


# ---- 英文稳定别名（并发脚本/外部探针友好） ----
@app.get("/api/reasonmap/version")
async def api_rm_version():
    return jsonify(目录.原因码映射状态())


@app.get("/api/reasonmap/reconcile")
async def api_rm_reconcile():
    return jsonify(目录.坏点匣对账报告())


@app.get("/api/reasonmap/report")
async def api_rm_report():
    return jsonify(目录.坏点匣对账报告())


@app.post("/api/reasonmap/promote")
async def api_rm_promote():
    body = await request.get_json(force=True, silent=True) or {}
    编号 = body.get("报文编号") or body.get("ref") or body.get("id") or ""
    return jsonify(目录.升格坏点(str(编号)))


@app.post("/api/reasonmap/cutover")
async def api_rm_cutover():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(目录.换版原因码映射(body))


@app.post("/api/reasonmap/inject-unknown")
async def api_rm_inject():
    body = await request.get_json(force=True, silent=True) or {}
    body.setdefault("未知", True)
    return jsonify(目录.注入坏点(body))


@app.get("/api/栏贯验")
async def api_贯验列表():
    return jsonify(目录.贯验列表())


@app.get("/api/夹具")
async def api_夹具():
    return jsonify(夹具.列表())


@app.post("/api/观测报文/装载")
async def api_装载():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(装载.装一批(body))


@app.post("/api/观测报文/夹具/<name>")
async def api_夹具装载(name: str):
    try:
        return jsonify(装载.装一批(夹具.读取(name)))
    except FileNotFoundError:
        return jsonify({"错误": name}), 404


@app.post("/api/结栏/跑")
async def api_结栏():
    return jsonify(结栏.结当前栏())


@app.get("/api/结栏/预览")
async def api_结栏预览():
    return jsonify(结栏.预览结栏())


@app.get("/api/栏贯验/快照")
async def api_贯验快照():
    return jsonify(贯验.只读快照())


@app.get("/api/夹具/预检")
async def api_夹具预检():
    return jsonify(夹具.全部预检())


@app.post("/api/栏贯验/跑")
async def api_贯验():
    return jsonify(贯验.跑一次())


@app.get("/api/统计/报文命运")
async def api_统计报文():
    return jsonify(统计.报文命运())


@app.get("/api/统计/缓冲命运")
async def api_统计缓冲():
    return jsonify(统计.缓冲命运())




@app.get("/api/装载批次")
async def api_装载批次():
    return jsonify(目录.装载批次列表())


@app.get("/api/结栏批次")
async def api_结栏批次():
    return jsonify(目录.结栏批次列表())


@app.get("/api/统计/按站点")
async def api_按站点():
    return jsonify(统计.按站点报文())


@app.get("/api/统计/按指标")
async def api_按指标():
    return jsonify(统计.按指标汇总())


@app.get("/api/统计/装载摘要")
async def api_装载摘要():
    return jsonify(统计.装载批次摘要())


@app.get("/api/统计/结栏摘要")
async def api_结栏摘要():
    return jsonify(统计.结栏批次摘要())

@app.get("/api/空桩")
async def api_空桩():
    root = Path(__file__).resolve().parent / "modules"
    out = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if p.is_dir() and p.name != "__pycache__" and (p / "__init__.py").is_file():
                out.append(p.name)
    return jsonify({"空桩": out, "条数": len(out)})


@app.get("/<path:name>")
async def static_page(name: str):
    p = _STATIC / name
    if not p.is_file():
        return redirect("/")
    return await send_from_directory(_STATIC, name)


@app.get("/api/reasonmap/看板")
async def api_reasonmap_board():
    return jsonify(reasonmap_svc.dashboard())


@app.post("/api/reasonmap/动作")
async def api_reasonmap_action():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(reasonmap_svc.commit_action(body))


@app.post("/api/reasonmap/半修展示")
async def api_reasonmap_half():
    return jsonify(reasonmap_svc.half_fix_display())


@app.get("/api/reasonmap/切流")
async def api_reasonmap_cut():
    return jsonify(reasonmap_cut_svc.board())


@app.post("/api/reasonmap/切流")
async def api_reasonmap_cut_post():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(reasonmap_cut_svc.append_cutover(int(body.get("ref_id") or 1), str(body.get("note") or "")))


@app.get("/api/reasonmap/双写")
async def api_reasonmap_dual():
    return jsonify(reasonmap_dual_svc.dual_board())


@app.post("/api/reasonmap/双写")
async def api_reasonmap_dual_post():
    body = await request.get_json(force=True, silent=True) or {}
    return jsonify(reasonmap_dual_svc.apply_dualwrite(str(body.get("note") or "")))


@app.get("/api/reasonmap/审计")
async def api_reasonmap_audit():
    return jsonify(reasonmap_audit_svc.audit_summary())
