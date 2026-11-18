import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from . import config
from .auth import hash_password
from .db import Base, SessionLocal, engine
from .models import User
from .api import (auth_api, sites, points, live, history, alarms, pages, dbview, backup, system,
                  video, health, users, zlm_hook, upload, scada, fpt, custom_objects,
                  video_sources, publish, gateways)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="Plant SCADA", version="1.1")

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

for r in (auth_api.router, users.router, sites.router, points.router, live.router,
          history.router, alarms.router, pages.router, video.router, health.router,
          zlm_hook.router, upload.router, scada.router, fpt.router,
          custom_objects.router, video_sources.router, publish.router,
          gateways.router, dbview.router, backup.router, system.router):
    app.include_router(r)

# 首次登录未改密时仍然放行的接口（否则用户无法完成改密）
PWD_WHITELIST = {
    "/api/auth/login", "/api/auth/me", "/api/auth/change-pwd",
    "/api/health", "/docs", "/openapi.json",
}


@app.middleware("http")
async def force_change_password(request: Request, call_next):
    """登录返回 must_change_pwd=true 时，除改密相关接口外一律 403（P1-4）"""
    path = request.url.path
    if not path.startswith("/api/") or path in PWD_WHITELIST:
        return await call_next(request)
    if path.startswith("/api/user/") and path.endswith("/password"):
        return await call_next(request)

    auth = request.headers.get("authorization", "")
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    elif request.query_params.get("token"):
        token = request.query_params.get("token")   # SSE 只能把 token 放 query
    if token:
        try:
            payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALG])
            username = payload.get("sub")
        except JWTError:
            username = None
        if username:
            def _must_change():
                db = SessionLocal()
                try:
                    u = db.query(User).filter(User.username == username).first()
                    return bool(u and u.pwd_updated_at is None)
                finally:
                    db.close()
            if await run_in_threadpool(_must_change):
                return JSONResponse(status_code=403,
                                    content={"detail": "must_change_password"})
    return await call_next(request)


@app.on_event("startup")
def bootstrap():
    # 建表（幂等）+ 首次创建 admin + 巡检账号
    Base.metadata.create_all(engine)
    # P5：sys_op_log 补 result 列（create_all 不会改已存在的表，只能就地 ALTER）
    try:
        with engine.begin() as conn:
            cols = [r[0] for r in conn.execute(text("show columns from sys_op_log"))]
            if "result" not in cols:
                conn.execute(text("alter table sys_op_log add column result varchar(16) null after new_val"))
                log.info("sys_op_log 已补 result 列")
    except Exception as e:
        log.warning("sys_op_log 补列跳过：%s", e)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "admin").count() == 0:
            db.add(User(username="admin",
                        pwd_hash=hash_password("Admin@2026"),
                        real_name="管理员", role_code="admin",
                        pwd_updated_at=None))   # 首次登录强制改密
            db.commit()
            log.info("已创建初始管理员 admin / Admin@2026（登录后强制改密）")

        # 巡检账号：给 verify.sh / 定时巡检用，避免把 admin 的强制改密流程卡住
        if os.getenv("VERIFY_BOT", "1") == "1":
            if db.query(User).filter(User.username == "checker").count() == 0:
                db.add(User(username="checker",
                            pwd_hash=hash_password(os.getenv("ADMIN_PWD") or "admin123"),
                            real_name="巡检账号", role_code="admin",
                            pwd_updated_at=__import__("datetime").datetime.now()))
                db.commit()
                log.info("已创建巡检账号 checker（供 verify.sh 自动化使用）")
    finally:
        db.close()
