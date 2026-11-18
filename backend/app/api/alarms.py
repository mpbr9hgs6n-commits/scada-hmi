"""报警：列表 / 确认 / 关闭 / 事件流水 / SSE 实时订阅

报警窗控件（P6 AlarmControl）的数据都从这里来：
- 首次连接：/api/alarm/subscribe 先推一帧 snapshot（当前活动报警）
- 之后：状态机每次变化 XADD 到 stream:alarms，SSE 增量推 act=raise/update/recover/ack/close
轮询 5 秒的后果是操作员看到报警时已经过去 5 秒，所以这里必须是推送。
"""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db, redis_client
from ..models import Alarm, AlarmEvent, OpLog, Point, User
from ..auth import get_current_user, check_site_permission, site_scope_ids
from ..core import alarm_engine

router = APIRouter(prefix="/api", tags=["alarms"])

LEVEL_NAME = {1: "提示", 2: "报警", 3: "严重"}
STATE_NAME = {0: "未确认", 1: "已确认", 2: "已恢复", 3: "已关闭"}


def client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


def _ser(a: Alarm, names=None):
    return {
        "id": a.id, "site_id": a.site_id, "point_code": a.point_code,
        "name": (names or {}).get((a.site_id, a.point_code)) or a.point_code,
        "level": a.level, "level_name": LEVEL_NAME.get(a.level, str(a.level)),
        "state": a.state, "state_name": STATE_NAME.get(a.state, str(a.state)),
        "val": a.val, "threshold": a.threshold, "msg": a.msg,
        "first_ts": str(a.first_ts or ""), "last_ts": str(a.last_ts or ""),
        "count": a.count, "ack_user": a.ack_user or "",
        "ack_ts": str(a.ack_ts or ""),
    }


def _names(db: Session, rows):
    """点位中文名：报警窗的「内容」列要显示「液位 超出上限 3.5」，不是 S001.LEVEL"""
    sites = {a.site_id for a in rows}
    if not sites:
        return {}
    pts = db.query(Point.site_id, Point.code, Point.name).filter(Point.site_id.in_(sites)).all()
    return {(p[0], p[1]): p[2] for p in pts}


@router.get("/alarms")
def list_alarms(state: int = None, level: int = None, site: str = None,
                unacked: int = 0, page: int = 1, size: int = 20,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Alarm)
    if state is not None:
        q = q.filter(Alarm.state == state)
    if unacked:
        q = q.filter(Alarm.state == 0)
    if level is not None:
        q = q.filter(Alarm.level == level)
    if site:
        check_site_permission(user, site, db)
        q = q.filter(Alarm.site_id == site)
    else:
        scope = site_scope_ids(user, db)
        if scope is not None:
            if not scope:
                return {"total": 0, "items": []}
            q = q.filter(Alarm.site_id.in_(scope))
    total = q.count()
    rows = q.order_by(Alarm.last_ts.desc()).offset((page - 1) * size).limit(size).all()
    names = _names(db, rows)
    return {"total": total, "items": [_ser(a, names) for a in rows]}


def _log(db: Session, user: User, a: Alarm, action: str, ip: str, result: str = "ok"):
    db.add(OpLog(username=user.username, site_id=a.site_id, point_code=a.point_code,
                 action=action, old_val=str(a.state), new_val="", ip=ip or "", result=result))


@router.post("/alarm/{aid}/ack")
def ack_alarm(aid: int, request: Request, body: dict = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = (body or {}).get("note", "")
    a0 = db.query(Alarm).filter(Alarm.id == aid).first()
    if not a0:
        raise HTTPException(404, "报警不存在")
    check_site_permission(user, a0.site_id, db)
    if a0.state == 3:
        raise HTTPException(400, "报警已关闭，不能再确认")
    a = alarm_engine.ack(db, aid, user.username, note)
    if not a:
        raise HTTPException(404, "报警不存在")
    _log(db, user, a, "alarm_ack", client_ip(request))
    db.commit()
    return {"ok": True, "id": a.id, "state": a.state,
            "state_name": STATE_NAME.get(a.state), "ack_user": a.ack_user}


@router.post("/alarm/{aid}/close")
def close_alarm(aid: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    a0 = db.query(Alarm).filter(Alarm.id == aid).first()
    if not a0:
        raise HTTPException(404, "报警不存在")
    check_site_permission(user, a0.site_id, db)
    a = alarm_engine.close(db, aid, user.username)
    if not a:
        raise HTTPException(404, "报警不存在")
    _log(db, user, a, "alarm_close", client_ip(request))
    db.commit()
    return {"ok": True, "id": a.id, "state": a.state, "state_name": STATE_NAME.get(a.state)}


@router.get("/alarm/events")
def alarm_events(alarm_id: int = None, site: str = None, page: int = 1, size: int = 50,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(AlarmEvent)
    if alarm_id:
        q = q.filter(AlarmEvent.alarm_id == alarm_id)
    if site:
        check_site_permission(user, site, db)
        q = q.filter(AlarmEvent.site_id == site)
    else:
        scope = site_scope_ids(user, db)
        if scope is not None:
            if not scope:
                return {"total": 0, "items": []}
            q = q.filter(AlarmEvent.site_id.in_(scope))
    total = q.count()
    rows = q.order_by(AlarmEvent.ts.desc()).offset((page - 1) * size).limit(size).all()
    return {"total": total, "items": [{
        "id": e.id, "alarm_id": e.alarm_id, "site_id": e.site_id,
        "point_code": e.point_code, "action": e.action, "val": e.val,
        "user_name": e.user_name, "note": e.note, "ts": str(e.ts or "")} for e in rows]}


def _snapshot_sync(site: str, scope):
    """SSE 生成器跑在事件循环里，DB 查询丢线程池。
    Session 不是线程安全的 —— 这里自己开一个短连接，不复用请求里的那个 db。"""
    from ..db import SessionLocal
    d = SessionLocal()
    try:
        q = d.query(Alarm).filter(Alarm.state.in_([0, 1, 2]))
        if site:
            q = q.filter(Alarm.site_id == site)
        elif scope is not None:
            q = q.filter(Alarm.site_id.in_(scope)) if scope else q.filter(Alarm.id < 0)
        rows = q.order_by(Alarm.last_ts.desc()).limit(200).all()
        names = _names(d, rows)
        return {"site": site, "total": len(rows),
                "items": [_ser(a, names) for a in rows]}
    finally:
        d.close()


@router.get("/alarm/subscribe")
async def alarm_subscribe(token: str = None, site: str = "", db: Session = Depends(get_db)):
    """SSE：首帧 snapshot + 增量。token 走 query —— EventSource 带不了 Header。"""
    from jose import jwt, JWTError
    from .. import config
    if not token:
        raise HTTPException(401, "缺少 token")
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALG])
    except JWTError:
        raise HTTPException(401, "登录已过期")
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    if site:
        check_site_permission(user, site, db)
    scope = site_scope_ids(user, db)

    async def gen():
        yield "retry: 3000\n\n"
        # 先记游标再取快照：中间新产生的那几条会在增量里再来一遍，
        # 前端按 id upsert，重复一条无害；反过来（先快照后取游标）会丢事件。
        try:
            top = await redis_client.xrevrange("stream:alarms", count=1)
            last_id = top[0][0] if top else "$"
        except Exception:
            last_id = "$"
        try:
            s0 = await asyncio.to_thread(_snapshot_sync, site, scope)
            yield f"event: snapshot\ndata: {json.dumps(s0, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'msg': str(e)[:200]})}\n\n"

        last_flush = time.monotonic()
        while True:
            try:
                items = await redis_client.xread({"stream:alarms": last_id},
                                                 block=1000, count=200)
            except Exception:
                items = []
            if items:
                for _key, entries in items:
                    for eid, d in entries:
                        last_id = eid
                        yield f"event: alarm\ndata: {json.dumps(d, ensure_ascii=False)}\n\n"
                last_flush = time.monotonic()
            elif time.monotonic() - last_flush >= 15:
                last_flush = time.monotonic()
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
