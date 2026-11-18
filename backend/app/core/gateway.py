# -*- coding: utf-8 -*-
"""后端 → 网关 的统一通道（原来在 api/devices.py，设备层删除后挪到 core）。

- gw_request：代理到网关，网关挂了给明确原因（不能吞成 500）
- notify_reload：配置变更后让网关增量重载该站点（不重启容器、不动别的站点）
"""
import httpx

from .. import config


async def gw_request(path: str, method: str = "GET", body: dict = None,
                     timeout: float = 15, gw_id: str = None):
    """gw_id 为空时打默认网关（config.GATEWAY_URL），否则打 gateway-{gw_id}。

    为什么必须带 gw_id：PLC 的 TCP 连接握在采集它的那个网关进程里。
    写点位/测试连接打到别的网关，它手里没有这台 PLC 的连接，只会超时。
    """
    base = config.gateway_api_url(gw_id)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.request(method, base + path, json=body)
            return r.json()
    except Exception as e:
        return {"ok": False, "error": f"网关不可达（{e}）",
                "hint": f"docker ps 看 gateway-{gw_id or '默认'} 是否在运行；"
                        f"docker logs 查原因"}


def gateway_of_site(site_id: str) -> str:
    """查站点归哪个网关。查不到返回空串（调用方回落到默认网关）。"""
    try:
        from ..db import SessionLocal
        from ..models import Site
        db = SessionLocal()
        try:
            s = db.query(Site).filter(Site.id == site_id).first()
            return (s.gateway_id or "") if s else ""
        finally:
            db.close()
    except Exception:
        return ""


async def notify_reload(site_id: str):
    """让**站点所属网关**重载这一个站点（增量，不是全量重启）。

    失败只记日志不上抛：配置已落库，网关恢复后会全量加载；调用方不该因为
    网关暂时不可达就回滚配置。
    """
    gw = gateway_of_site(site_id)
    r = await gw_request(f"/internal/reload?site={site_id}", "POST", timeout=8, gw_id=gw)
    if not r.get("ok"):
        import logging
        logging.getLogger("app.gateway").warning(
            "站点 %s 热重载通知失败（配置已保存）：%s", site_id, r.get("error"))
    return r
