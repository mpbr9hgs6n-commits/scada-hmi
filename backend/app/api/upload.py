"""组态背景图上传（P3）

只有背景图需要后端存文件，其余属性都写进画面 json。

安全取舍：
- 上传要登录 + 编辑角色；读图公开（CSS background-image / <img> 带不了 Authorization 头）。
  文件名是 32 位随机 hex，不可枚举；目录穿越由文件名白名单正则挡掉。
- 不收 SVG：SVG 能内嵌脚本，直接当图片挂到页面上等于开了个 XSS 口子。
"""
import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..auth import get_current_user
from ..models import User

router = APIRouter(prefix="/api", tags=["upload"])

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads")
MAX_SIZE = 5 * 1024 * 1024
EDIT_ROLES = ("admin", "operator")

# 扩展名 -> (Content-Type, 文件头校验)
CT_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
}
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")
MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}


def _magic_ok(ext: str, data: bytes) -> bool:
    if ext == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return any(data.startswith(m) for m in MAGIC[ext])


@router.post("/upload")
async def upload_image(req: Request, user: User = Depends(get_current_user)):
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限，不能上传")

    ct = (req.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = CT_EXT.get(ct)
    if not ext:
        raise HTTPException(400, "只支持 PNG / JPEG / WebP / GIF 图片")

    try:
        declared = int(req.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_SIZE:
        raise HTTPException(413, "图片超过 5MB，请先压缩")

    data = await req.body()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "图片超过 5MB，请先压缩")
    if not _magic_ok(ext, data):
        raise HTTPException(400, "文件内容与图片格式不符")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    name = uuid.uuid4().hex + ext
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return {"ok": True, "url": "/api/upload/" + name, "size": len(data)}


@router.get("/upload/{name}")
def get_image(name: str):
    # 只认 32 位随机名：目录穿越与枚举都被挡住
    if not NAME_RE.match(name or ""):
        raise HTTPException(404, "图片不存在")
    path = os.path.join(UPLOAD_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "图片不存在")
    ext = name.rsplit(".", 1)[1]
    return FileResponse(path, media_type=MEDIA[ext],
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
