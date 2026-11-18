import asyncio, json, time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db, redis_client
from ..models import Point, User
from ..auth import get_current_user, check_site_permission
from ..core.realtime import merge_by_point

router = APIRouter(prefix="/api", tags=["live"])

@router.get("/live/subscribe")
async def subscribe(site: str, token: str = None, db: Session = Depends(get_db)):
    """SSE：订阅 stream:changes，按点位合并推送；15s 心跳"""
    from ..auth import get_current_user
    from fastapi import Request
    # SSE 无法带 Header，改用 query token
    from jose import jwt, JWTError
    from .. import config
    from ..models import User
    if not token:
        raise HTTPException(401, "缺少 token")
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALG])
    except JWTError:
        raise HTTPException(401, "登录已过期")
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    check_site_permission(user, site, db)

    async def gen():
        last_id = "$"
        yield "retry: 3000\n\n"
        buf, last_flush = [], time.monotonic()
        while True:
            try:
                items = await redis_client.xread({"stream:changes": last_id},
                                                 block=1000, count=500)
            except Exception:
                items = []
            if items:
                for stream_key, entries in items:
                    for entry_id, d in entries:
                        last_id = entry_id
                        buf.append((entry_id, d))
            now = time.monotonic()
            if buf and (now - last_flush >= 0.1 or len(buf) > 200):
                merged = merge_by_point(buf)
                buf.clear(); last_flush = now
                # 只推订阅者自己站点的数据。
                # stream:changes 是全平台的总线（200 站混在一条 stream 里），
                # 不过滤的话订阅 S001 的人会收到 S006 的数据，前端按 site 过滤后全丢，
                # 表现就是「SSE 连着但画面永远不动」。
                rows = [m for m in merged if m.get("site") == site]
                if rows:
                    yield f"event: delta\ndata: {json.dumps(rows)}\n\n"
            elif not buf and now - last_flush >= 15:
                last_flush = now
                yield ": keepalive\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
