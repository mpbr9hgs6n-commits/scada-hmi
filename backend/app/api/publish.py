# -*- coding: utf-8 -*-
"""14 号：发布入口（免登录，给现场 Kiosk / 值班大屏用）。

为什么单独一个模块而不复用 /api/page：
  - `/api/page/{id}` 是编辑器用的，要能读草稿（published=0）
  - 发布入口是公开的，必须**只**能读已发布的画面，否则别人猜 id 就能看未发布内容
  - 所以两个接口分开，权限边界清晰

授权模型：
  - `GET /api/publish/tree`        完全公开（和 /view/:id 一样，电视没人登录）
  - `GET /api/publish/page/{pid}`  公开，但 published=0 一律 404
"""
import json
import logging
import secrets
from datetime import datetime, timedelta

from jose import jwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..models import Page, Site, User
from .pages import _has_thumb

log = logging.getLogger("publish")
router = APIRouter(prefix="/api/publish", tags=["publish"])


def _site_names(db: Session) -> dict:
    """{site_id: 站点名}，用来给目录树的站点节点起名"""
    return {s.id: (s.name or s.id) for s in db.query(Site).all()}


@router.get("/tree")
def publish_tree(db: Session = Depends(get_db)):
    """发布入口的目录树数据：站点 → 画面。

    用户要求「目录树按站点分组，一个站点可以有多个页面」——这里就是按 site_id 分组。
    没设站点的画面归到「未分类」，保证不漏。
    """
    rows = (db.query(Page)
              .filter(Page.kind == "scada", Page.published == 1)
              .order_by(Page.pub_sort, Page.id)
              .all())

    names = _site_names(db)
    groups = {}          # site_id -> {site_name, pages[]}
    order = []           # 保持稳定顺序：有站点的按站点 id，最后是未分类

    for p in rows:
        sid = p.site_id or ""
        if sid not in groups:
            groups[sid] = {
                "site_id": p.site_id or None,
                "site_name": names.get(sid) or "未分类",
                "pages": [],
            }
            order.append(sid)
        groups[sid]["pages"].append({
            "id": p.id,
            "name": p.name,
            "thumb": f"/api/page/{p.id}/thumb.png",
            "has_thumb": _has_thumb(p.id),
        })

    # 未分类排最后
    order.sort(key=lambda x: (x == "", x))
    out = [groups[k] for k in order]

    return {
        "groups": out,
        "total": len(rows),
        "group_count": len(out),
    }


@router.get("/token")
def publish_token(db: Session = Depends(get_db)):
    """发布入口的只读 token（长期有效）。

    为什么需要这个：
      现场 Kiosk 电视没人登录，但 `/api/site/{sid}/snapshot`、`/api/valuelists`、
      `/api/video/cameras` 这些数据接口都强制要 JWT。没有 token 就会 401，
      而前端的 401 拦截器会把人踢回登录页——发布入口就废了。

    设计取舍：
      - 发一个 `viewer` 角色（只读）的长期 token，10 年有效
      - 自动建 `kiosk` 账号（密码随机，不告诉任何人，只靠 token 访问）
      - ⚠ 这个接口是公开的，等同"匿名可读"——内网部署可接受；
        要收紧的话，可以加来源 IP 白名单或改成固定 token 存 sys_config
    """
    # 有任意组态画面才发 token（/view/:id 也用它，不要求已发布）
    # 完全不发会让 /view/:id 卡在「加载中…」，发太宽又等于裸奔，这里取中间：
    # 系统里至少存在一张 scada 画面才给，且 token 只有 viewer 读权限。
    n = db.query(Page).filter(Page.kind == "scada").count()
    if not n:
        raise HTTPException(404, "系统里还没有组态画面")

    u = db.query(User).filter(User.username == "kiosk").first()
    if not u:
        from ..auth import hash_password
        u = User(username="kiosk",
                 pwd_hash=hash_password(secrets.token_urlsafe(32)),
                 real_name="发布入口只读账号",
                 role_code="viewer",
                 status=1,
                 pwd_updated_at=datetime.now())   # 避免被判为"首次登录需改密"
        db.add(u)
        db.commit()
        db.refresh(u)
        log.info("已创建 kiosk 只读账号（发布入口用）")

    exp = datetime.utcnow() + timedelta(days=3650)
    tok = jwt.encode({"sub": "kiosk", "exp": exp},
                     config.JWT_SECRET, algorithm=config.JWT_ALG)
    return {"token": tok, "user": "kiosk", "role": "viewer",
            "exp": int(exp.timestamp())}


@router.get("/page/{pid}")
def publish_page(pid: int, db: Session = Depends(get_db)):
    """发布态读画面内容。只返回 published=1 的，否则 404（防猜 id）。"""
    p = (db.query(Page)
           .filter(Page.id == pid, Page.kind == "scada", Page.published == 1)
           .first())
    if not p:
        raise HTTPException(404, "画面不存在或未发布")

    try:
        j = json.loads(p.json) if isinstance(p.json, str) else (p.json or {})
    except Exception:
        j = {}

    return {
        "id": p.id,
        "name": p.name,
        "site_id": p.site_id,
        "json": j,
        "updated_at": str(p.updated_at or ""),
    }
