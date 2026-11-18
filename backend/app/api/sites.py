# -*- coding: utf-8 -*-
"""站点管理（提示词 09：一个站点 = 一台 PLC，没有设备层）。

PLC 参数直接挂在 site 上；测试连接代理到网关（协议库装在网关容器里，
backend 容器连不到真 PLC 的网段）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, redis_client
from ..models import Site, Point, User, Gateway
from ..auth import get_current_user, check_site_permission, site_scope_ids
from ..core.realtime import hget_all
from ..core.gateway import gw_request, notify_reload
from ..core.addr import addr_span
import asyncio

router = APIRouter(prefix="/api", tags=["sites"])

# 站点表可写的 PLC/描述字段（列表与编辑共用一套，防止编辑页少字段反向覆盖）
SITE_FIELDS = ("name", "gateway_id", "group_id", "address", "remark", "location",
               "brand", "series", "comm_mode", "plc_protocol", "plc_ip",
               "plc_port", "rack", "slot", "slave_id", "enabled", "merge_addr",
               "max_batch", "offline_threshold", "serial_params",
               "proto_params",
               # 提示词 10：心跳判定
               "heartbeat_mode", "hb_write_addr", "hb_read_addr",
               "hb_max_value", "hb_cycles", "ping_interval_ms",
               "hb_write_port", "hb_read_port", "hb_interval_s")

# 心跳模式（单选）：none 关闭 / modbus_echo 回环 / ping 网络探测
HB_MODES = ("none", "modbus_echo", "ping")

VALID_PROTOCOLS = {"s7", "mc", "mc_1e", "mc_3e", "modbus_tcp", "modbus_rtu",
                   "fins", "opcua", "cip", "ab_eth"}

# 协议默认端口（与前端 protocolSchema.js 同源）
PROTO_DEFAULT_PORT = {"s7": 102, "mc": 5000, "mc_1e": 4999, "mc_3e": 5000,
                      "modbus_tcp": 502, "modbus_rtu": 502, "fins": 9600,
                      "ab_eth": 44818, "cip": 44818, "opcua": 4840}


def _params_of(v):
    """proto_params/serial_params 是 MySQLJSON 列：SQLAlchemy 读出来已经是 dict；
    迁移期可能是 JSON 字符串，两种都要能吃。"""
    if not v:
        return {}
    if isinstance(v, dict):
        return v
    import json as _json
    try:
        x = _json.loads(v)
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}


def _row(s: Site, point_count: int = None, stats: dict = None):
    stats = stats or {}
    return {"id": s.id, "name": s.name, "group_id": s.group_id,
            "address": s.address, "location": s.location, "remark": s.remark,
            "plc_protocol": s.plc_protocol, "plc_ip": s.plc_ip,
            "gateway_id": s.gateway_id,
            "plc_port": s.plc_port,
            "brand": s.brand, "series": s.series,
            "comm_mode": s.comm_mode or "tcp",
            "rack": s.rack or 0, "slot": s.slot if s.slot is not None else 1,
            "slave_id": s.slave_id if s.slave_id is not None else 1,
            "enabled": s.enabled if s.enabled is not None else 1,
            "merge_addr": s.merge_addr if s.merge_addr is not None else 1,
            "max_batch": s.max_batch or 120,
            "offline_threshold": s.offline_threshold or 3,
            # 心跳（提示词 10）
            "heartbeat_mode": s.heartbeat_mode or "none",
            "hb_write_addr": s.hb_write_addr if s.hb_write_addr is not None else 0,
            "hb_read_addr": s.hb_read_addr if s.hb_read_addr is not None else 1,
            "hb_max_value": s.hb_max_value or 2000,
            "hb_cycles": s.hb_cycles or 3,
            "hb_write_port": s.hb_write_port,
            "hb_read_port": s.hb_read_port,
            "hb_interval_s": s.hb_interval_s or 0,
            "ping_interval_ms": s.ping_interval_ms or 5000,
            "proto_params": _params_of(s.proto_params),
            "serial_params": _params_of(s.serial_params),
            "status": s.status or 0,
            "last_err": stats.get("last_err", s.last_err),
            "succ_rate": stats.get("succ_rate", s.succ_rate),
            "online": stats.get("online"),
            "point_count": point_count,
            "created_at": str(s.created_at or "")}


def _require_edit(user: User):
    if user.role_code not in ("admin", "operator"):
        raise HTTPException(403, "仅管理员/操作员可配置站点")


def _hb_validate(db: Session, site_id: str, data: dict, protocol: str):
    """校验心跳配置（提示词 10 第 2 节）并返回 (patch, warning)。

    - 模式单选；modbus_echo 只对 modbus_tcp 有效，其他协议自动降级 ping
    - 数值范围：hb_max_value 1~2000、hb_cycles 1~10、ping 间隔 1000~60000
    - 回环读写地址必须与业务点位不重叠（按保持寄存器 HR 的 0-based 偏移比）
    """
    def _int(k, dflt, lo, hi, label):
        try:
            v = int(data.get(k, dflt))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{label} 必须是整数")
        if not (lo <= v <= hi):
            raise HTTPException(400, f"{label} 必须在 {lo}~{hi} 之间（收到 {v}）")
        return v

    mode = (data.get("heartbeat_mode") or "none").strip()
    if mode not in HB_MODES:
        raise HTTPException(400, f"heartbeat_mode 只能是 {'/'.join(HB_MODES)}")
    warn = ""
    w = _int("hb_write_addr", 0, 0, 65535, "心跳写地址")
    r = _int("hb_read_addr", 1, 0, 65535, "心跳读地址")
    mx = _int("hb_max_value", 2000, 1, 2000, "心跳循环上限")
    cyc = _int("hb_cycles", 3, 1, 10, "心跳判定周期数")
    iv = _int("ping_interval_ms", 5000, 1000, 60000, "ping 间隔")

    # 双端口：留空 = 用站点 plc_port（同端口回环，复用采集连接）
    def _port_opt(k, label):
        v = data.get(k)
        if v is None or v == "":
            return None
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{label} 必须是整数")
        if not (1 <= v <= 65535):
            raise HTTPException(400, f"{label} 必须在 1~65535 之间（收到 {v}）")
        return v

    wp = _port_opt("hb_write_port", "心跳写入端口")
    rp = _port_opt("hb_read_port", "心跳读取端口")
    # 回环间隔：0 = 每轮采集都跑；>0 = 独立按秒跑
    hi = _int("hb_interval_s", 0, 0, 3600, "心跳间隔(秒)")

    # 🔴 心跳是**独立通道**，与采集协议无关：
    #    S7 / MC 站点一样可以配 Modbus 回环心跳（采集走 102/4999，心跳走 506/507），
    #    用来确认 PLC 没假死。所以这里**不按 plc_protocol 降级**，只要求端口能定下来。
    if mode == "modbus_echo" and not wp and not rp:
        if (protocol or "").lower() != "modbus_tcp":
            raise HTTPException(
                400, "Modbus 回环心跳需要填写「写入端口」或「读取端口」"
                     "（该站采集协议不是 Modbus，无法默认端口）")
    # 同地址 + 同端口 = 恒等回环。不拦，只提示——判定条件只看「写入值 == 读回值」，
    # 其余由现场决定。
    same_conn = (wp or 0) == (rp or 0)
    if mode == "modbus_echo" and w == r and same_conn:
        warn = ("同端口同地址是恒等回环（写什么读什么，永远在线），"
                "看不出 PLC 停机；建议读回地址换成另一个由 PLC 程序搬运的寄存器")
    if mode != "modbus_echo" and (wp or rp or hi):
        warn = "端口/间隔只在 Modbus 回环模式下生效，已保存但不使用"
    patch = {"heartbeat_mode": mode, "hb_write_addr": w, "hb_read_addr": r,
             "hb_max_value": mx, "hb_cycles": cyc, "ping_interval_ms": iv,
             "hb_write_port": wp, "hb_read_port": rp, "hb_interval_s": hi}
    if mode == "modbus_echo" and site_id:
        from ..core.addr import addr_span
        for p in db.query(Point).filter(Point.site_id == site_id).all():
            try:
                area, s0, s1 = addr_span("modbus_tcp", p.addr, p.dtype)
            except Exception:
                continue
            if area != "HR":
                continue
            for hb, label in ((w, "写地址"), (r, "读回地址")):
                if s0 <= hb < s1:
                    raise HTTPException(400, f"心跳{label} HR{hb} 与点位 {p.code}"
                                             f"（{p.addr}）占用重叠，换一个空闲地址")
    return patch, warn


# 同一个站点同一时刻只允许一个测试连接（提示词 10 第 1 节规则 6）
_test_locks = {}


def _site_test_lock(sid: str) -> asyncio.Lock:
    lk = _test_locks.get(sid)
    if lk is None:
        lk = asyncio.Lock()
        _test_locks[sid] = lk
    return lk


@router.get("/sites")
async def list_sites(kw: str = "", group: int = None, status: int = None,
               page: int = 1, size: int = 20,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scope = site_scope_ids(user, db)
    if scope is not None and not scope:
        return {"total": 0, "items": []}
    q = db.query(Site)
    if scope is not None:
        q = q.filter(Site.id.in_(scope))
    if kw:
        q = q.filter(Site.name.contains(kw) | Site.id.contains(kw)
                     | Site.plc_ip.contains(kw))
    if group is not None:
        q = q.filter(Site.group_id == group)
    if status is not None:
        q = q.filter(Site.status == status)
    total = q.count()
    rows = q.order_by(Site.id).offset((page - 1) * size).limit(size).all()
    # 在线状态：网关心跳把结果写在 Redis site:status:{id}（1=在线 2=离线）。
    # 之前这里没填，导致前端 online 恒为 null，发布页没法按离线灰度。
    # 缺这个 key 说明该站点没配心跳（hb_mode=none），保持 None 由前端当"未知"处理。
    online_map = {}
    try:
        keys = [f"site:status:{s.id}" for s in rows]
        if keys:
            vals = await redis_client.mget(keys)
            for s2, v in zip(rows, vals):
                if v is None:
                    continue
                online_map[s2.id] = (str(v) == "1")
    except Exception:
        online_map = {}

    items = []
    for s in rows:
        n = db.query(Point).filter(Point.site_id == s.id).count()
        st = {"online": online_map[s.id]} if s.id in online_map else {}
        items.append(_row(s, point_count=n, stats=st))
    return {"total": total, "items": items}


@router.get("/sites/status")
async def sites_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """采集侧在线状态：并发查所有网关再合并（每个网关只知道自己那几个站点）。"""
    gids = [g.id for g in db.query(Gateway).order_by(Gateway.id).all()] or [None]
    results = await asyncio.gather(
        *[gw_request("/api/status", timeout=4, gw_id=g) for g in gids],
        return_exceptions=True)
    scope = site_scope_ids(user, db)
    items, hist = [], 0
    for gid, data in zip(gids, results):
        if isinstance(data, Exception) or not isinstance(data, dict) or data.get("error"):
            continue
        hist += int(data.get("hist_written") or 0)
        for d in data.get("sites", []):
            if scope is None or d["site"] in scope:
                items.append({"site": d["site"], "online": d["online"],
                              "gateway_id": gid or "",
                              "hb_mode": d.get("hb_mode", "none"),
                              "hb_state": d.get("hb_state", "unknown"),
                              "points": d.get("points", 0),
                              "round_requests": d.get("round_requests", 0)})
    return {"items": items, "hist_written": hist}


@router.get("/site/{site_id}")
def get_site(site_id: str, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    check_site_permission(user, site_id, db)
    s = db.query(Site).filter(Site.id == site_id).first()
    if not s:
        raise HTTPException(404, "站点不存在")
    n = db.query(Point).filter(Point.site_id == site_id).count()
    n_store = db.query(Point).filter(Point.site_id == site_id,
                                     Point.save_history == 1).count()
    n_rw = db.query(Point).filter(Point.site_id == site_id, Point.rw == 1).count()
    out = _row(s, point_count=n)
    out["point_stats"] = {"total": n, "store": n_store, "rw": n_rw}
    return out


MAX_SITES_PER_GATEWAY = 20      # 一个网关最多挂 20 台 PLC


def _require_gateway(db, gateway_id, site_id=None):
    """站点必须归到某个网关；一个网关最多 20 台 PLC。

    用户要求（2026-11-12）：不指定网关不能保存。
    为什么要卡 20 台：现场一台 PLC 的连接槽很少，网关并发连太多会把槽抢满，
    表现为"平台和编程软件都连不上"，排查成本极高。这个上限是硬拦，不做提示放行。
    """
    gid = (gateway_id or "").strip()
    if not gid:
        raise HTTPException(400, "必须指定所属网关（不指定不能保存）")
    gw = db.query(Gateway).filter(Gateway.id == gid).first()
    if not gw:
        raise HTTPException(400, f"网关 {gid} 不存在")
    q = db.query(Site).filter(Site.gateway_id == gid)
    if site_id:
        q = q.filter(Site.id != site_id)      # 改自己不算新增一台
    n = q.count()
    if n >= MAX_SITES_PER_GATEWAY:
        raise HTTPException(
            400, f"网关 {gid} 已挂 {n} 台 PLC，上限 {MAX_SITES_PER_GATEWAY} 台")
    return gid


@router.post("/site")
async def create_site(body: dict, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    # 社区版额度：每网关最多 MAX_SITES 台 PLC（= 站点数）
    from ..core import edition as _ed
    _n = db.query(Site).count()
    if _ed.sites_full(_n):
        raise HTTPException(403, _ed.sites_message(_n))
    _require_edit(user)
    sid = (body.get("id") or "").strip()
    if not sid:
        raise HTTPException(400, "站点编号不能为空")
    if db.query(Site).filter(Site.id == sid).first():
        raise HTTPException(400, "站点编号已存在")
    proto = body.get("plc_protocol") or body.get("protocol") or "modbus_tcp"
    if proto not in VALID_PROTOCOLS:
        raise HTTPException(400, f"不支持的协议: {proto}")
    ip = (body.get("plc_ip") or "").strip()
    if not ip:
        raise HTTPException(400, "PLC 地址不能为空（一个站点就是一台 PLC）")
    # 同一台 PLC 不允许出现在两个站点（提示词 2.1 约束：plc_ip 唯一）
    dup = db.query(Site).filter(Site.plc_ip == ip,
                                Site.plc_port == int(body.get("plc_port")
                                                     or PROTO_DEFAULT_PORT.get(proto, 502))).first()
    if dup:
        raise HTTPException(400, f"PLC {ip}:{body.get('plc_port')} 已被站点 {dup.id} 使用"
                                 f"（一台 PLC 只能属于一个站点）")
    port = int(body.get("plc_port") or PROTO_DEFAULT_PORT.get(proto, 502))
    gid = _require_gateway(db, body.get("gateway_id"))
    s = Site(id=sid, name=body.get("name") or sid, gateway_id=gid,
             plc_protocol=proto, plc_ip=ip, plc_port=port)
    for k in SITE_FIELDS:
        if k in body and k not in ("plc_ip", "plc_port", "plc_protocol"):
            setattr(s, k, body[k])
    if "protocol" in body and "plc_protocol" not in body:
        s.plc_protocol = body["protocol"]
    hb_patch, hb_warn = _hb_validate(db, sid, body, proto)
    for k, v in hb_patch.items():
        setattr(s, k, v)
    db.add(s)
    db.commit()
    rr = await notify_reload(sid)
    return {"ok": True, "id": s.id, "warning": hb_warn,
            "reload_ok": bool((rr or {}).get("ok")),
            "reload_err": "" if (rr or {}).get("ok") else str((rr or {}).get("error") or "网关未响应（容器可能没在运行）")[:160]}


@router.put("/site/{site_id}")
async def update_site(site_id: str, body: dict, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    _require_edit(user)
    s = db.query(Site).filter(Site.id == site_id).first()
    if not s:
        raise HTTPException(404, "站点不存在")
    # 网关变更也要校验（必填 + 上限）。只有请求里带了 gateway_id 才校验，
    # 避免"只改备注"被历史空值卡住。
    if "gateway_id" in body:
        body["gateway_id"] = _require_gateway(db, body.get("gateway_id"), site_id)
    plc_changed = False
    for k in SITE_FIELDS:
        if k in body:
            setattr(s, k, body[k])
            if k in ("plc_ip", "plc_port", "plc_protocol", "rack", "slot",
                     "slave_id", "proto_params",
                     "enabled", "comm_mode", "serial_params"):
                plc_changed = True
    if "protocol" in body:
        s.plc_protocol = body["protocol"]
    # 心跳配置校验：只有请求里带了心跳字段才校验（老前端编辑页不带就不动）
    hb_warn = ""
    HB_KEYS = ("heartbeat_mode", "hb_write_addr", "hb_read_addr",
               "hb_max_value", "hb_cycles", "ping_interval_ms",
               "hb_write_port", "hb_read_port", "hb_interval_s")
    if any(k in body for k in HB_KEYS):
        # 注意：merged 必须把**所有**心跳字段都带上，否则新加的端口/间隔会在
        # 「读旧值→并请求→校验→回写」这条链上被丢掉（表现为保存成功但查出来是空的）
        merged = {k: getattr(s, k) for k in HB_KEYS}
        merged.update({k: body[k] for k in HB_KEYS if k in body})
        hb_patch, hb_warn = _hb_validate(db, site_id, merged, s.plc_protocol)
        for k, v in hb_patch.items():
            setattr(s, k, v)
        plc_changed = True          # 心跳参数变了，网关要重载
    db.commit()
    rr = None
    if plc_changed:
        rr = await notify_reload(site_id)
    return {"ok": True, "warning": hb_warn,
            "reload_ok": True if not plc_changed else bool((rr or {}).get("ok")),
            "reload_err": "" if (not plc_changed or (rr or {}).get("ok"))
                          else str((rr or {}).get("error") or "网关未响应（容器可能没在运行）")[:160]}


async def _do_delete_site(db: Session, site_id: str, confirm: int):
    """单站删除内部实现：级联删点位、清 Redis 实时键、通知网关热加载。
    TDengine 历史子表与数据一律保留（与单删语义一致）。
    返回 (成功?, 失败原因, 删除点位数)。"""
    s = db.query(Site).filter(Site.id == site_id).first()
    if not s:
        return False, "站点不存在", 0
    n = db.query(Point).filter(Point.site_id == site_id).count()
    if n and not confirm:
        return False, f"有 {n} 个点位，需确认（confirm=1）才连同删除", n
    db.query(Point).filter(Point.site_id == site_id).delete()
    db.delete(s)
    db.commit()
    try:
        await redis_client.delete(f"rt:{site_id}")
    except Exception:
        pass
    await notify_reload(site_id)
    return True, "", n


@router.delete("/site/batch")
async def delete_sites_batch(body: dict, confirm: int = 0,
                             db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    """批量删除站点：逐个执行，不允许「部分失败但不告知」。
    路由必须定义在 /site/{site_id} 之前，否则 batch 被动态路由吞掉。"""
    if user.role_code != "admin":
        raise HTTPException(403, "仅管理员可删除站点")
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    deleted, failed, total_points = [], [], 0
    for sid in ids:
        ok, msg, n = await _do_delete_site(db, str(sid), confirm)
        if ok:
            deleted.append(sid)
            total_points += n
        else:
            failed.append({"id": sid, "reason": msg})
    return {"ok": True, "deleted": deleted, "failed": failed,
            "deleted_points": total_points}


@router.delete("/site/{site_id}")
async def delete_site(site_id: str, confirm: int = 0,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """级联删点位（提示词 09 第 5 节：需二次确认 → confirm=1）。
    Redis 实时键一起删；TDengine 历史子表与数据一律保留。"""
    if user.role_code != "admin":
        raise HTTPException(403, "仅管理员可删除站点")
    ok, msg, n = await _do_delete_site(db, site_id, confirm)
    if not ok:
        raise HTTPException(404 if msg == "站点不存在" else 400, msg)
    return {"ok": True, "deleted_points": n}


@router.post("/site/{site_id}/test")
async def test_site(site_id: str, body: dict = None, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """测试连接（提示词 10 第 1 节）：body 里的临时参数优先，**不读写数据库**。

    body: {protocol, ip, port, rack, slot, slave_id, timeout_ms, addr, dtype}
    - 参数缺省取站点已保存值（兼容老调用）
    - addr/dtype 缺省取该站点第一个 enabled 点位 → sample 证明「真读到值」
    - 同一站点同一时刻只允许一个测试（PLC 连接数宝贵）
    """
    check_site_permission(user, site_id, db)
    s = db.query(Site).filter(Site.id == site_id).first()
    if not s:
        raise HTTPException(404, "站点不存在")
    body = body or {}

    lock = _site_test_lock(site_id)
    if lock.locked():
        raise HTTPException(409, "该站点正在测试中，请等上一次测试结束（防占满 PLC 连接数）")
    await lock.acquire()
    try:
        proto = (body.get("protocol") or body.get("plc_protocol") or s.plc_protocol or "").lower()
        ip = (body.get("ip") or body.get("plc_ip") or s.plc_ip or "").strip()
        port = int(body.get("port") if body.get("port") is not None
                   else (body.get("plc_port") if body.get("plc_port") is not None
                         else (s.plc_port or 0)))
        addr, dtype = body.get("addr"), body.get("dtype")
        if not addr:
            first = (db.query(Point).filter(Point.site_id == site_id, Point.enabled == 1)
                     .order_by(Point.sort_no, Point.id).first())
            if first:
                addr, dtype = first.addr, first.dtype
        payload = {"protocol": proto, "ip": ip, "port": port,
                   "slave_id": int(body.get("slave_id") or s.slave_id or 1),
                   "rack": int(body.get("rack") or s.rack or 0),
                   "slot": int(body.get("slot") if body.get("slot") is not None
                               else (s.slot if s.slot is not None else 1)),
                   "series": body.get("series") or s.series or "",
                   "timeout_ms": 3000,   # 固定 3 秒，不再从请求/配置取
                   "proto_params": _params_of(body.get("proto_params") or s.proto_params),
                   "addr": addr or "", "dtype": dtype or "float32"}
        out = await gw_request("/api/testconn", "POST", payload, timeout=20,
                               gw_id=getattr(s, "gateway_id", None))
    finally:
        lock.release()

    ok = bool(out.get("ok"))
    # 统一响应：ok / elapsed_ms / sample / error（其余字段保留给旧前端与验收脚本）
    return {**out,
            "ok": ok,
            "elapsed_ms": out.get("latency_ms") or 0,
            "sample": out.get("read_value"),
            "error": "" if ok else (out.get("error") or "连接失败"),
            "hint": out.get("hint") or "",
            "tested": {"protocol": proto, "ip": ip, "port": port,
                       "rack": payload["rack"], "slot": payload["slot"],
                       "slave_id": payload["slave_id"], "timeout_ms": payload["timeout_ms"],
                       "addr": addr or "", "dtype": dtype or "float32"}}


@router.post("/site/{site_id}/test/apply")
async def test_site_apply(site_id: str, body: dict, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """把测试通过的参数写回站点并热加载（提示词 10 第 1 节 1.3）"""
    _require_edit(user)
    s = db.query(Site).filter(Site.id == site_id).first()
    if not s:
        raise HTTPException(404, "站点不存在")
    proto = (body.get("protocol") or body.get("plc_protocol") or s.plc_protocol or "").lower()
    if proto not in VALID_PROTOCOLS:
        raise HTTPException(400, f"不支持的协议: {proto}")
    mapping = (("ip", "plc_ip"), ("port", "plc_port"), ("rack", "rack"),
               ("slot", "slot"), ("slave_id", "slave_id"),
               ("timeout_ms", "timeout_ms"))
    changed = {}
    for src, col in mapping:
        v = body.get(src)
        if v is None or v == "":
            continue
        if col in ("plc_ip",):
            v = str(v).strip()
            if not v:
                continue
        else:
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{src} 必须是整数")
        if getattr(s, col) != v:
            setattr(s, col, v)
            changed[col] = v
    if s.plc_protocol != proto:
        s.plc_protocol = proto
        changed["plc_protocol"] = proto
    db.commit()
    await notify_reload(site_id)
    return {"ok": True, "reloaded": True, "changed": changed}


@router.post("/site/test")
async def test_site_form(body: dict, user: User = Depends(get_current_user)):
    """表单现填参数直接测（站点还没保存也行）——参数原样转发给网关"""
    _require_edit(user)
    if not body.get("ip"):
        raise HTTPException(400, "IP 不能为空")
    return await gw_request("/api/testconn", "POST", body, timeout=20,
                            gw_id=body.get("gateway_id"))


@router.get("/site/{site_id}/snapshot")
async def snapshot(site_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """SSE 断线兜底：全量实时值快照（只读 Redis，不查 MySQL 取实时值）"""
    check_site_permission(user, site_id, db)
    values = await hget_all(redis_client, site_id)
    site = db.query(Site).filter(Site.id == site_id).first()
    # 有效采集周期：点位没单独设就用内置值（站点参数里已经没有「采集周期」这一项）。
    # 前端用它算 stale 阈值（poll×3）；60s 周期的点位会带自己的 poll_ms，不受影响。
    dflt_ms = 1000
    pts = db.query(Point).filter(Point.site_id == site_id).all()
    out = {}
    for p in pts:
        v = values.get(p.code)
        out[p.code] = {"name": p.name, "unit": p.unit, "decimals": p.decimals,
                       "val": round(v["val"], p.decimals) if v else None,
                       "ts": v["ts"] if v else 0, "q": v["q"] if v else 0,
                       "rw": p.rw, "dtype": p.dtype,
                       "poll_ms": p.poll_ms or dflt_ms}
    return {"site": site_id, "ts": __import__("time").time() * 1000, "values": out}
