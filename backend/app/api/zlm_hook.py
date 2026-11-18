# -*- coding: utf-8 -*-
"""ZLM hook 鉴权（安全整改 03）

ZLM 在客户端播放/推流时会回调这些地址，只有返回 JSON {"code": 0} 才放行。
注意：这是 ZLM 自己的约定（code=0 成功），**不是 HTTP 状态码**，返回 401 状态码没用。

token 由后端 HMAC-SHA256 签，格式 "{exp}.{sig}"，只对指定 stream 有效：
- play    scope：前端播放，默认 5 分钟（VIDEO_TOKEN_TTL）
- publish scope：内部推流；演示流用固定的 PUBLISH_TOKEN（不过期，只在 .env / 容器内）

安全边界：
- hook 地址只允许 ZLM 从容器内网直连 backend:8000；带 X-Forwarded-For 的一律拒绝
  （nginx 那边也有 location /api/zlm/ 直接 403，双保险）
"""
import hashlib
import hmac
import time
import urllib.parse

from fastapi import APIRouter, Request

from .. import config

router = APIRouter(prefix="/api/zlm", tags=["zlm-hook"])

DENY_CODE = 401


def _secret() -> bytes:
    return (config.VIDEO_TOKEN_SECRET or config.JWT_SECRET).encode()


def sign(stream: str, scope: str = "play", ttl: int = None) -> dict:
    """给指定 stream 签一个短期 token"""
    exp = int(time.time()) + (ttl if ttl is not None else config.VIDEO_TOKEN_TTL)
    msg = f"{scope}:{stream}:{exp}".encode()
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]
    return {"token": f"{exp}.{sig}", "exp": exp}


def verify(stream: str, token: str, scope: str = "play") -> bool:
    """校验 token：签名对得上、没过期、且是给这个 stream 签的"""
    if not token or "." not in token:
        return False
    exp_s, sig = token.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    msg = f"{scope}:{stream}:{exp}".encode()
    want = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(want, sig)


def _params(params) -> dict:
    """ZLM 把 url 上的 query 原样放在 params 字段里，形如 token=xxx&foo=1"""
    raw = params or ""
    if not isinstance(raw, str):
        return {}
    try:
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items() if v}
    except Exception:
        return {}


async def _payload(req: Request) -> dict:
    """ZLM 的 hook 是 POST JSON（实测 content-type: application/json），
    老版本/某些场景才是 form 表单，所以两种都接。"""
    ct = (req.headers.get("content-type") or "").lower()
    if "json" in ct:
        try:
            d = await req.json()
        except Exception:
            return {}
        if not isinstance(d, dict):
            return {}
        return {k: ("" if v is None else str(v)) for k, v in d.items()}
    try:
        f = await req.form()
    except Exception:
        return {}
    return {k: ("" if v is None else str(v)) for k, v in f.items()}


async def _hook(req: Request, scope: str):
    if req.headers.get("x-forwarded-for") or req.headers.get("x-real-ip"):
        return {"code": DENY_CODE, "msg": "hook only accepts internal direct call"}
    data = await _payload(req)
    stream = (data.get("stream") or "").strip()
    if not stream:
        return {"code": DENY_CODE, "msg": "no stream"}
    tok = _params(data.get("params")).get("token", "")
    if verify(stream, tok, scope):
        return {"code": 0, "msg": "ok"}
    if scope == "publish" and config.PUBLISH_TOKEN and \
            hmac.compare_digest(tok, config.PUBLISH_TOKEN):
        return {"code": 0, "msg": "ok(service)"}
    return {"code": DENY_CODE, "msg": "no auth"}


@router.post("/on_play")
async def on_play(req: Request):
    """有人拉流（http-flv/hls/rtsp）时触发"""
    return await _hook(req, "play")


@router.post("/on_publish")
async def on_publish(req: Request):
    """有人推流时触发，防止往流媒体服务里推垃圾流"""
    return await _hook(req, "publish")
