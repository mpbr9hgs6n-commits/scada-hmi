import httpx, time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .. import config
from ..db import get_db, engine, redis_client, td_query
from ..models import User
from ..auth import get_current_user

router = APIRouter(prefix="/api", tags=["health"])

async def _gw_ok():
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            # 用轻量 /api/ping，避免 20 万点位时序列化 status 拖慢健康检查
            r = await c.get(config.GATEWAY_URL + "/api/ping")
            return r.status_code == 200 and r.json().get("ok") is True
    except Exception:
        return False

async def _zlm_ok():
    try:
        from ..core.zlm import zlm_get
        data = await zlm_get("/index/api/getServerConfig")
        return data.get("code") == 0
    except Exception as e:
        return False

@router.get("/health")
async def health():
    out = {"status": "ok", "ts": int(time.time() * 1000)}
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        out["db"] = "ok"
    except Exception as e:
        out["db"] = f"fail: {e}"; out["status"] = "degraded"
    try:
        await redis_client.ping()
        out["redis"] = "ok"
    except Exception as e:
        out["redis"] = f"fail: {e}"; out["status"] = "degraded"
    try:
        await td_query("show databases")
        out["tdengine"] = "ok"
    except Exception as e:
        out["tdengine"] = f"fail: {e}"; out["status"] = "degraded"
    out["gw"] = "ok" if await _gw_ok() else "fail"
    out["zlm"] = "ok" if await _zlm_ok() else "fail"
    if out["gw"] != "ok" or out["zlm"] != "ok":
        out["status"] = "degraded"
    return out

@router.post("/write")
async def write_point(body: dict, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """写 PLC（P5 写回链路：rw 校验 → 写 → 200ms 回读 → 比对 → 记审计）

    失败一律给可读的中文 detail，前端直接 toast —— 组态里"点了没反应"是不能接受的。
    """
    if user.role_code == "viewer":
        raise HTTPException(403, "只读账号禁止下发控制")
    from ..models import Point, Site, OpLog
    from ..auth import check_site_permission
    from ..core.realtime import hget_all
    site, code, val = body.get("site"), body.get("point"), body.get("value")
    if not all(x is not None for x in (site, code, val)):
        raise HTTPException(400, "site/point/value 必填")
    check_site_permission(user, site, db)
    # 先分清是「站点不在了」还是「点位不在了」——两者都报「点位不存在」
    # 时，现场根本没法判断该去查站点还是查点位。
    st = db.query(Site).filter(Site.id == site).first()
    if not st:
        raise HTTPException(404, f"站点 {site} 不存在（可能已被删除）")
    if st.enabled != 1:
        raise HTTPException(400, f"站点 {site} 已停用（enabled=0），不采集也就不能下发")
    p = db.query(Point).filter(Point.site_id == site, Point.code == code).first()
    if not p:
        n = db.query(Point).filter(Point.site_id == site).count()
        raise HTTPException(404, f"点位 {code} 不在站点 {site} 里（该站点共 {n} 个点位）")
    if p.enabled != 1:
        raise HTTPException(400, f"点位 {code} 已停用（enabled=0），不采集也就不能下发")
    if p.rw != 1:
        raise HTTPException(400, "该点位只读，禁止写入")

    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else ""))

    old = None
    try:
        vals = await hget_all(redis_client, site)
        if code in vals:
            old = vals[code]["val"]
    except Exception:
        old = None

    def audit(result, new_val):
        db.add(OpLog(username=user.username, site_id=site, point_code=code,
                     action="write", old_val=str(old), new_val=str(new_val),
                     ip=ip, result=result))
        db.commit()

    # 写 → 回读：网关内部 sleep 200ms 再读寄存器，不一致直接 400 带「写入X 读回Y」
    from ..core.gateway import gateway_of_site
    gw_of_site = gateway_of_site(site)
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            # 必须发给**站点所属**的网关：PLC 连接在它手里，
            # 发给别的网关会得到「本网关没有采集站点 XXX」。
            r = await c.post(config.gateway_api_url(gw_of_site) + "/write",
                             json={"site": site, "point": code, "value": val})
    except (httpx.ConnectError, httpx.ConnectTimeout):
        audit("fail:gw_down", val)
        raise HTTPException(503, "写入超时，请检查网关（连不上采集网关）")
    except httpx.TimeoutException:
        audit("fail:timeout", val)
        raise HTTPException(504, "写入超时，请检查网关")

    ms = int((time.time() - t0) * 1000)
    if r.status_code != 200:
        txt = ""
        try:
            txt = (r.json() or {}).get("detail", "") or r.text
        except Exception:
            txt = r.text
        txt = str(txt)[:200]
        if "回读不一致" in txt:
            audit("fail:mismatch", val)
            # 把网关的「回读不一致：写入1 读回0」整理成操作员看得懂的话
            back = txt.split("读回")[-1] if "读回" in txt else "?"
            raise HTTPException(409, "写入失败：回读为 " + back)
        audit("fail:gw", val)
        # 网关返回的 txt 本身可能是「写入失败：xxx」，别再加一遍变成「写入失败：写入失败：」
        raise HTTPException(400, txt if txt.startswith("写入失败") else "写入失败：" + txt)

    result = r.json()
    back = result.get("value")
    audit("ok", back)
    return {"ok": True, "value": back, "old": old, "match": True, "ms": ms}
