# -*- coding: utf-8 -*-
"""采集网关管理（2026-11-12 多网关方案）

一个网关一套独立 TDengine，共享 MySQL / Redis。
站点在 site.gateway_id 上指明归属，网关启动时读 GATEWAY_ID 环境变量
只加载属于自己的站点（collector.load_config）。
"""
import asyncio
import re

import httpx
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from .. import config
from ..db import get_db
from ..models import Gateway, Site, User

router = APIRouter(prefix="/api", tags=["gateway"])

MAX_SITES_PER_GATEWAY = 20      # 与 sites.py 保持一致


def _require_admin(user: User):
    if (getattr(user, "role_code", "") or "") != "admin":
        raise HTTPException(403, "只有管理员能管理网关")


def _row(g: Gateway, n_sites: int, online=None):
    return {
        "id": g.id, "name": g.name,
        "tdengine_url": g.tdengine_url,
        "remark": g.remark or "",
        "sites": n_sites,
        # online: 网关进程是不是真的在跑。None = 本次没探测（单站查询时不需要）
        "online": online,
        "created_at": g.created_at.strftime("%Y-%m-%d %H:%M:%S") if g.created_at else "",
    }


async def _probe_online(gid: str) -> bool:
    """探一下网关进程在不在（2 秒超时，不拖垮列表）。

    这一步很重要：网关只在库里登记、容器没起时，站点分给它就没人采，
    写点位还会报「点位不存在」—— 列表上必须一眼看出来。
    """
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(config.gateway_api_url(gid) + "/api/status")
            return r.status_code == 200
    except Exception:
        return False


@router.get("/gateways")
async def list_gateways(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """网关列表 + 每个网关已挂多少台 PLC + 运行状态"""
    gs = db.query(Gateway).order_by(Gateway.id).all()
    counts = {}
    for sid, gid in db.query(Site.id, Site.gateway_id).all():
        if gid:
            counts[gid] = counts.get(gid, 0) + 1
    onlines = await asyncio.gather(*[_probe_online(g.id) for g in gs],
                                   return_exceptions=True)
    return {"items": [_row(g, counts.get(g.id, 0),
                          None if isinstance(onlines[i], Exception) else bool(onlines[i]))
                      for i, g in enumerate(gs)],
            "max_sites": MAX_SITES_PER_GATEWAY}


@router.post("/gateway")
def create_gateway(body: dict, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_admin(user)
    gid = (body.get("id") or "").strip()
    if not gid:
        raise HTTPException(400, "网关标识不能为空（例：gw2）")
    # 只允许 ASCII：它要拼进容器名 gateway-{id}、DNS 名 tdengine-{id}、环境变量名。
    # 不能用 str.isalnum() —— 那玩意把中文也当字母，放"网关二"过去会生成
    # http://tdengine-网关二:6041 这种非法地址，连删除都会因为 URL 编码报 ascii 错。
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$", gid):
        raise HTTPException(400, "网关标识只能用英文字母、数字、下划线、短横，"
                                 "并且必须以字母或数字开头（例：gw2）")
    if db.query(Gateway).filter(Gateway.id == gid).first():
        raise HTTPException(400, f"网关 {gid} 已存在")
    # TDengine 地址由系统按网关标识自动生成，不接受手填。
    # 规则：gw1 沿用现有实例，gwN 用 tdengine-gwN。特殊部署靠环境变量 TDENGINE_URL_GWN 覆盖。
    url = config.tdengine_url_of(gid)
    g = Gateway(id=gid, name=(body.get("name") or gid).strip()[:64],
                tdengine_url=url, remark=(body.get("remark") or "")[:255],
                created_at=datetime.now())
    db.add(g)
    db.commit()
    return {"ok": True, "id": g.id}


@router.put("/gateway/{gid}")
def update_gateway(gid: str, body: dict, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _require_admin(user)
    g = db.query(Gateway).filter(Gateway.id == gid).first()
    if not g:
        raise HTTPException(404, "网关不存在")
    if "name" in body:
        g.name = (body.get("name") or gid).strip()[:64]
    # 地址不让改：它由网关标识推导，改了就和实际部署对不上。
    # 真需要换实例就设环境变量 TDENGINE_URL_{GID}，然后重建后端容器。
    _ = body.get("tdengine_url", None)
    if "remark" in body:
        g.remark = (body.get("remark") or "")[:255]
    db.commit()
    n = db.query(Site).filter(Site.gateway_id == gid).count()
    return {"ok": True, **_row(g, n)}


@router.delete("/gateway/{gid}")
def delete_gateway(gid: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """还有站点挂着的网关不能删 —— 删了那些站点就没人采了。"""
    _require_admin(user)
    g = db.query(Gateway).filter(Gateway.id == gid).first()
    if not g:
        raise HTTPException(404, "网关不存在")
    n = db.query(Site).filter(Site.gateway_id == gid).count()
    if n:
        raise HTTPException(400, f"网关 {gid} 还挂着 {n} 台 PLC，先把站点改到别的网关再删")
    db.delete(g)
    db.commit()
    return {"ok": True}
