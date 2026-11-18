from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from . import config
from .db import get_db
from .models import User, UserSite

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

def hash_password(p: str) -> str:
    return pwd_ctx.hash(p)

def verify_password(p: str, h: str) -> bool:
    try:
        return pwd_ctx.verify(p, h)
    except Exception:
        return False

def make_token(user: User) -> str:
    payload = {"sub": user.username, "uid": user.id, "role": user.role_code,
               "exp": datetime.utcnow() + timedelta(hours=config.JWT_EXP_H)}
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALG)

def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise HTTPException(401, "未登录")
    try:
        payload = jwt.decode(cred.credentials, config.JWT_SECRET, algorithms=[config.JWT_ALG])
    except JWTError:
        raise HTTPException(401, "登录已过期")
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if not user or user.status != 1:
        raise HTTPException(401, "用户不存在或已禁用")
    return user

def check_site_permission(user: User, site_id: str, db: Session):
    """admin/operator 全站；site_op 只能管授权站点；viewer 只读不校验写"""
    if user.role_code in ("admin", "operator"):
        return
    if user.role_code == "site_op":
        allowed = db.query(UserSite).filter(UserSite.user_id == user.id,
                                            UserSite.site_id == site_id).first()
        if not allowed:
            raise HTTPException(403, f"无站点 {site_id} 权限")
    # viewer 只读；写操作由 write 类接口另行校验


def site_scope_ids(user: User, db: Session):
    """列表类接口用：返回该用户可见的站点 id 列表，None 表示不限。

    语义必须与 check_site_permission 完全一致，否则会出现
    「列表能看见、点进去 403」或者反过来「列表看不见、直连能读」的裂缝：
    - admin / operator：None（全站）
    - site_op：sys_user_site 里的授权站点（可能为空列表）
    - viewer：None（只读放行，与 check_site_permission 一致）
    """
    if user.role_code != "site_op":
        return None
    rows = db.query(UserSite.site_id).filter(UserSite.user_id == user.id).all()
    return [r[0] for r in rows]
