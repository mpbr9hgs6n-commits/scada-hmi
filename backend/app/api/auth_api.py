from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import User, LoginLog
from ..auth import verify_password, hash_password, make_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginIn(BaseModel):
    username: str
    password: str

class ChangePwdIn(BaseModel):
    old_password: str
    new_password: str

@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")[:250]
    if not user or not verify_password(body.password, user.pwd_hash):
        db.add(LoginLog(username=body.username, ip=ip, ua=ua, ok=0, reason="密码错误"))
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    if user.status != 1:
        raise HTTPException(403, "账号已禁用")
    db.add(LoginLog(username=user.username, ip=ip, ua=ua, ok=1, reason="ok"))
    db.commit()
    return {"token": make_token(user),
            "user": {"id": user.id, "username": user.username,
                     "real_name": user.real_name, "role": user.role_code},
            "must_change_pwd": user.pwd_updated_at is None}

@router.post("/change-pwd")
def change_pwd(body: ChangePwdIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    from .users import check_pwd_policy
    if not verify_password(body.old_password, user.pwd_hash):
        raise HTTPException(400, "原密码错误")
    check_pwd_policy(body.new_password)
    if verify_password(body.new_password, user.pwd_hash):
        raise HTTPException(400, "新密码不能与原密码相同")
    user.pwd_hash = hash_password(body.new_password)
    user.pwd_updated_at = __import__("datetime").datetime.now()
    db.commit()
    return {"ok": True}

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "real_name": user.real_name,
            "role": user.role_code, "must_change_pwd": user.pwd_updated_at is None}
