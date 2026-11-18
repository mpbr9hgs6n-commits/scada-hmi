"""ZLMediaKit 新版 API 登录辅助：digest 两步登录，返回带 cookie 的 client"""
import hashlib, re
import httpx
from .. import config

def _zlm_base():
    return config.ZLM_URL

async def zlm_client() -> httpx.AsyncClient:
    """登录并返回带 ZLM_LOGINED cookie 的 client（用完需 aclose）"""
    c = httpx.AsyncClient(timeout=10)
    base = _zlm_base()
    # 第一次：拿未登录 cookie（必须带 digest 参数才走到发 cookie 的逻辑）
    r = await c.get(f"{base}/index/api/login", params={"digest": "init"})
    m = re.search(r'"cookie"\s*:\s*"([^"]+)"', r.text)
    if not m:
        return c
    un = m.group(1)
    digest = hashlib.md5(f"zlmediakit:{config.ZLM_SECRET}:{un}".encode()).hexdigest()
    await c.get(f"{base}/index/api/login",
                params={"digest": digest},
                headers={"Cookie": f"ZLM_UNLOGIN={un}"})
    return c

async def zlm_get(path: str, **params) -> dict:
    c = await zlm_client()
    try:
        r = await c.get(_zlm_base() + path, params=params or None)
        return r.json()
    finally:
        await c.aclose()
