"""用户管理：/api/users 系列（对齐验收报告 P0-3）
   权限：写操作仅 admin；operator 只能改自己密码；viewer 只读
"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, Role, LoginLog, OpLog
from ..auth import get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["users"])

PWD_RULE = "密码至少 10 位，且必须包含大写字母、小写字母、数字和特殊字符"


def check_pwd_policy(pwd: str):
    """新密码策略：≥10 位 + 大写 + 小写 + 数字 + 特殊字符"""
    if len(pwd or "") < 10:
        raise HTTPException(400, PWD_RULE)
    if not re.search(r"[A-Z]", pwd):
        raise HTTPException(400, PWD_RULE)
    if not re.search(r"[a-z]", pwd):
        raise HTTPException(400, PWD_RULE)
    if not re.search(r"\d", pwd):
        raise HTTPException(400, PWD_RULE)
    if not re.search(r"[^A-Za-z0-9]", pwd):
        raise HTTPException(400, PWD_RULE)


def require_admin(user: User):
    if user.role_code != "admin":
        raise HTTPException(403, "仅管理员可执行该操作")


def user_dict(u: User, last_login=None):
    return {"id": u.id, "username": u.username, "real_name": u.real_name,
            "role": u.role_code, "role_code": u.role_code,
            "phone": u.phone, "enabled": u.status, "status": u.status,
            "must_change_pwd": u.pwd_updated_at is None,
            "last_login": str(last_login) if last_login else "",
            "created_at": str(u.created_at or "")}


def last_login_map(db: Session):
    rows = (db.query(LoginLog.username, func.max(LoginLog.ts))
              .filter(LoginLog.ok == 1).group_by(LoginLog.username).all())
    return {name: ts for name, ts in rows}


class UserIn(BaseModel):
    username: str
    password: str = None
    real_name: str = None
    role: str = "viewer"
    phone: str = None
    enabled: int = 1


class UserUpd(BaseModel):
    real_name: str = None
    role: str = None
    phone: str = None
    enabled: int = None


class PwdIn(BaseModel):
    old_password: str = None
    new_password: str


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_admin(user)
    lm = last_login_map(db)
    rows = db.query(User).order_by(User.id).all()
    return {"total": len(rows), "items": [user_dict(u, lm.get(u.username)) for u in rows]}


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Role).order_by(Role.code).all()
    return {"items": [{"code": r.code, "name": r.name, "perms": r.perms} for r in rows]}


@router.post("/user")
def create_user(body: UserIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    require_admin(user)
    if not body.username or len(body.username) < 3:
        raise HTTPException(400, "用户名至少 3 位")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "用户名已存在")
    if not body.password:
        raise HTTPException(400, "必须设置初始密码")
    check_pwd_policy(body.password)
    if body.role not in ("admin", "operator", "viewer", "site_op"):
        raise HTTPException(400, "角色不合法")
    u = User(username=body.username, pwd_hash=hash_password(body.password),
             real_name=body.real_name, role_code=body.role, phone=body.phone,
             status=body.enabled, pwd_updated_at=None)   # 首次登录强制改密
    db.add(u)
    db.add(OpLog(username=user.username, action="新增用户", new_val=body.username,
                 ip=request.client.host if request.client else ""))
    db.commit()
    return {"ok": True, "id": u.id}


@router.put("/user/{uid}")
def update_user(uid: int, body: UserUpd, request: Request,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_admin(user)
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    if u.id == 1 and body.enabled == 0:
        raise HTTPException(400, "禁止停用内置管理员 admin")
    old = f"{u.real_name}|{u.role_code}|{u.status}"
    if body.real_name is not None:
        u.real_name = body.real_name
    if body.role is not None:
        if body.role not in ("admin", "operator", "viewer", "site_op"):
            raise HTTPException(400, "角色不合法")
        if u.id == 1 and body.role != "admin":
            raise HTTPException(400, "禁止降低内置管理员 admin 的角色")
        u.role_code = body.role
    if body.phone is not None:
        u.phone = body.phone
    if body.enabled is not None:
        u.status = body.enabled
    db.add(OpLog(username=user.username, action="修改用户", old_val=old,
                 new_val=f"{u.real_name}|{u.role_code}|{u.status}",
                 ip=request.client.host if request.client else ""))
    db.commit()
    return {"ok": True}


@router.put("/user/{uid}/password")
def change_user_pwd(uid: int, body: PwdIn, request: Request,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """改密码：本人改需验旧密码；admin 重置他人不需要旧密码"""
    is_self = (user.id == uid)
    if not is_self and user.role_code != "admin":
        raise HTTPException(403, "只能修改自己的密码")
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    if is_self:
        if not body.old_password or not verify_password(body.old_password, u.pwd_hash):
            raise HTTPException(400, "原密码错误")
    check_pwd_policy(body.new_password)
    if verify_password(body.new_password, u.pwd_hash):
        raise HTTPException(400, "新密码不能与原密码相同")
    u.pwd_hash = hash_password(body.new_password)
    u.pwd_updated_at = datetime.now()
    db.add(OpLog(username=user.username, action="修改密码",
                 new_val=u.username,
                 ip=request.client.host if request.client else ""))
    db.commit()
    return {"ok": True}


@router.delete("/user/{uid}")
def delete_user(uid: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """禁用账号（保留审计痕迹）；id=1 内置 admin 禁止操作"""
    require_admin(user)
    if uid == 1:
        raise HTTPException(400, "禁止删除内置管理员 admin")
    u = db.query(User).filter(User.id == uid).first()
    if not u:
        raise HTTPException(404, "用户不存在")
    u.status = 0
    db.add(OpLog(username=user.username, action="禁用用户", old_val=u.username,
                 ip=request.client.host if request.client else ""))
    db.commit()
    return {"ok": True, "enabled": 0}


@router.get("/login-logs")
def login_logs(size: int = 50, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    require_admin(user)
    rows = db.query(LoginLog).order_by(LoginLog.id.desc()).limit(size).all()
    return {"items": [{"id": r.id, "username": r.username, "ip": r.ip,
                       "ok": r.ok, "reason": r.reason, "ts": str(r.ts or "")}
                      for r in rows]}
