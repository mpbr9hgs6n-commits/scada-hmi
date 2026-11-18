# -*- coding: utf-8 -*-
"""对象库自定义图元（每组可加自己的图）。

为什么单独一张表而不是塞进画面 json：
  图元是**跨画面复用**的资产（做一次，所有画面都能拖），必须落库共享；
  而画面 json 里只保留引用（拖进去时生成 image 对象，src 指向已上传的图）。

图片上传走既有的 POST /api/upload（只收 PNG/JPEG/WebP/GIF，≤5MB，不收 SVG），
这里只记地址，不重复实现文件存储。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import CustomObject, User

router = APIRouter(prefix="/api", tags=["custom-object"])

EDIT_ROLES = ("admin", "operator")
# 对象库的 5 个分组（与前端 ObjectPalette 的 key 一一对应）
GROUP_KEYS = ("std", "smart", "craft", "deck", "ctrl", "sym")


def _row(o):
    return {"id": o.id, "group_key": o.group_key, "name": o.name,
            "image_url": o.image_url, "w": o.w or 120, "h": o.h or 60,
            "sort": o.sort or 0,
            "created_at": str(o.created_at or "")}


def _need_edit(user):
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")


@router.get("/custom-objects")
def list_objects(group: str = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """列出所有自定义图元（可按 group 过滤）。只读，任何登录用户都能看。"""
    q = db.query(CustomObject).filter(CustomObject.enabled == 1)
    if group:
        if group not in GROUP_KEYS:
            raise HTTPException(400, f"group 只能是 {'/'.join(GROUP_KEYS)}")
        q = q.filter(CustomObject.group_key == group)
    rows = q.order_by(CustomObject.sort, CustomObject.id).all()
    return {"items": [_row(o) for o in rows]}


@router.post("/custom-object")
def create_object(body: dict, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _need_edit(user)
    group = (body.get("group_key") or "craft").strip()
    if group not in GROUP_KEYS:
        raise HTTPException(400, f"group_key 只能是 {'/'.join(GROUP_KEYS)}")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "名称不能为空")
    if len(name) > 64:
        raise HTTPException(400, "名称最多 64 个字符")
    url = (body.get("image_url") or "").strip()
    if not url.startswith("/api/upload/"):
        raise HTTPException(400, "image_url 必须是 /api/upload/ 下的地址（先用上传接口传图）")

    # 同名去重：同一分组内名称唯一，避免对象库里两个「水泵」分不清
    dup = (db.query(CustomObject)
             .filter(CustomObject.group_key == group, CustomObject.name == name)
             .first())
    if dup:
        raise HTTPException(400, f"该分组下已存在名为「{name}」的图元")

    def _int(k, dflt, lo, hi):
        try:
            v = int(body.get(k, dflt))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{k} 必须是整数")
        if not (lo <= v <= hi):
            raise HTTPException(400, f"{k} 必须在 {lo}~{hi} 之间")
        return v

    o = CustomObject(
        group_key=group, name=name, image_url=url,
        w=_int("w", 120, 8, 2000), h=_int("h", 60, 8, 2000),
        sort=_int("sort", 0, 0, 9999),
        created_by=user.username, enabled=1)
    db.add(o)
    db.commit()
    db.refresh(o)
    return {"ok": True, "id": o.id}


@router.put("/custom-object/{oid}")
def update_object(oid: int, body: dict, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _need_edit(user)
    o = db.query(CustomObject).filter(CustomObject.id == oid).first()
    if not o:
        raise HTTPException(404, "图元不存在")

    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "名称不能为空")
        dup = (db.query(CustomObject)
                 .filter(CustomObject.group_key == o.group_key,
                         CustomObject.name == name,
                         CustomObject.id != oid).first())
        if dup:
            raise HTTPException(400, f"该分组下已存在名为「{name}」的图元")
        o.name = name[:64]

    if "image_url" in body:
        url = (body.get("image_url") or "").strip()
        if not url.startswith("/api/upload/"):
            raise HTTPException(400, "image_url 必须是 /api/upload/ 下的地址")
        o.image_url = url

    for k, lo, hi in (("w", 8, 2000), ("h", 8, 2000), ("sort", 0, 9999)):
        if k in body:
            try:
                v = int(body[k])
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} 必须是整数")
            if not (lo <= v <= hi):
                raise HTTPException(400, f"{k} 必须在 {lo}~{hi} 之间")
            setattr(o, k, v)

    if "group_key" in body:
        g = (body.get("group_key") or "").strip()
        if g not in GROUP_KEYS:
            raise HTTPException(400, f"group_key 只能是 {'/'.join(GROUP_KEYS)}")
        o.group_key = g

    db.commit()
    return {"ok": True}


@router.delete("/custom-object/{oid}")
def delete_object(oid: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """软删（enabled=0）：已拖进画面的对象仍能显示，只是对象库里不再出现。"""
    _need_edit(user)
    o = db.query(CustomObject).filter(CustomObject.id == oid).first()
    if not o:
        raise HTTPException(404, "图元不存在")
    o.enabled = 0
    db.commit()
    return {"ok": True}
