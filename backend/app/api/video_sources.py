# -*- coding: utf-8 -*-
"""监控视频接口程序：RTSP 设备/通道管理 + 探测 + 拉流控制 + 回放。

设计取舍：
- **RTSP 地址直接存完整 URL**（含账号密码，形如 rtsp://your_user:your_password@ip:554/...）：
  平台这边不再二次拼装，也不引入加密依赖；内网 + 只有管理员能看，风险可接受。
  如果以后要走「按品牌拼 URL」，camera 表里的 ip/port/username/brand 字段已经留好了。
- **探测不依赖本机 ffprobe**：backend 容器里没有 ffmpeg，ZLM 容器里有。
  所以探测 = 让 ZLM 临时拉一路流 → getMediaInfo 读编码/分辨率 → 立刻删掉这路代理。
- **回放走 NVR**（不是平台录）：项目既定「录像由 NVR 存」，所以按品牌生成
  NVR 的回放 RTSP 地址，再让 ZLM 拉流给浏览器播。
  直接明确报错，不假装能用。

流名规则：{site_id}-{序号}（序号 = sort_no + 1），与既有 /api/video/url 完全一致，
不改已有画面的引用。
"""
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import check_site_permission, get_current_user
from .. import config
from ..core.zlm import zlm_client
from ..db import get_db
from ..models import Camera, User

router = APIRouter(prefix="/api/video", tags=["video-sources"])

EDIT_ROLES = ("admin", "operator")
ZLM = config.ZLM_URL
VHOST = "__defaultVhost__"
APP = "live"


def _need_edit(user):
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无视频管理权限")


def _legacy_stream_of(cam):
    """老流名规则：{site}-{sort_no+1}。只用于兼容改动前保存的画面。"""
    return f"{cam.site_id}-{(cam.sort_no or 0) + 1}"


def _stream_of(cam, sub=False):
    """流名必须和显示顺序解耦。

    以前用 sort_no+1，调一下通道顺序，已配好的组态画面全部串台，
    而且不报任何错 —— 现场只会看到"视频窗显示的是别的摄像头"。
    改用数据库主键：唯一、创建后永不变。

    主码流 {site}-{id}，子码流 {site}-{id}-sub（两者要能同时被拉、同时被播）。
    """
    base = f"{cam.site_id}-{cam.id}"
    return f"{base}-sub" if sub else base


def _row(cam):
    return {
        "id": cam.id, "site_id": cam.site_id, "code": cam.code, "name": cam.name,
        "location": cam.location, "brand": cam.brand, "ip": cam.ip,
        "rtsp_port": cam.rtsp_port, "access_type": cam.access_type or "rtsp",
        "rtsp_main": cam.rtsp_main, "rtsp_sub": cam.rtsp_sub,
        "codec": cam.codec, "resolution": cam.resolution, "fps": cam.fps,
        "ptz": cam.ptz, "record_enable": cam.record_enable,
        "keep_days": cam.keep_days, "wall_slot": cam.wall_slot,
        "sort_no": cam.sort_no, "status": cam.status,
        "stream": _stream_of(cam),
        "stream_sub": _stream_of(cam, sub=True),
        "legacy_stream": _legacy_stream_of(cam),
        "codec_sub": cam.codec_sub or "",
        "browser_ok_sub": (cam.codec_sub or "").upper() == "H264" if cam.codec_sub else None,
        "rtsp_sub": cam.rtsp_sub or "",
        "sort_no": cam.sort_no or 0,
        "channel_no": cam.channel_no,
        "enabled": cam.enabled,
    }


def _mask_url(u):
    """返回给前端时把 URL 里的密码打码（rtsp://u:***@ip/...），编辑时前端不覆盖原值。"""
    if not u or "@" not in u:
        return u
    head, tail = u.split("@", 1)
    if "://" in head and ":" in head.split("://", 1)[1]:
        scheme, cred = head.split("://", 1)
        user_ = cred.split(":", 1)[0]
        return f"{scheme}://{user_}:******@{tail}"
    return u


@router.get("/site-channels")
def list_site_channels(site: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """轻量通道清单：只查库，不拉流、不探测。

    为什么要单独一个接口：
      `/api/video/cameras` 会触发 ZLM 拉流（为了拿播放地址），
      而「属性面板下拉」「视频墙格选路」只需要知道有哪些通道，
      下拉框每展开一次就拉一路流显然不合理。

    返回的 ch 就是 stream 末尾的数字（S001-3 → 3），和组态里填的序号一致。
    """
    check_site_permission(user, site, db)
    rows = (db.query(Camera)
              .filter(Camera.site_id == site, Camera.enabled == 1)
              .order_by(Camera.sort_no, Camera.id).all())
    out = []
    for c in rows:
        stream = _stream_of(c)
        stream_sub = _stream_of(c, sub=True)
        legacy = _legacy_stream_of(c)
        try:
            seq = int(legacy.rsplit("-", 1)[-1])       # ch 仍是老规则，兼容旧画面
        except (ValueError, IndexError):
            seq = 0
        out.append({
            "id": c.id,
            "ch": seq,                                  # 兼容老画面（sort_no+1）
            "stream": stream,                           # 主码流流名（主键派生）
            "stream_sub": stream_sub,                   # 子码流流名
            "legacy_stream": legacy,                    # 老流名，供 pickCam 兜底
            "name": c.name,
            "codec": c.codec,                           # 主码流编码（登记值）
            "codec_sub": c.codec_sub or "",             # 子码流编码
            "sort_no": c.sort_no or 0,
            "channel_no": c.channel_no,
            # 浏览器只认 H.264；H.265 即使通道在线，flv.js 也解不了
            "browser_ok": (c.codec or "").upper() != "H265",
            "browser_ok_sub": ((c.codec_sub or "").upper() == "H264") if c.codec_sub else None,
            "rtsp": _mask_url(c.rtsp_main),
            "rtsp_sub": _mask_url(c.rtsp_sub),
        })
    return {"site": site, "total": len(out), "items": out}


# ===================== 设备 / 通道管理 =====================
@router.get("/sources")
def list_sources(site: str = None, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    q = db.query(Camera).filter(Camera.enabled == 1)
    if site:
        check_site_permission(user, site, db)
        q = q.filter(Camera.site_id == site)
    rows = q.order_by(Camera.site_id, Camera.sort_no, Camera.id).all()
    out = []
    for c in rows:
        r = _row(c)
        r["rtsp_main"] = _mask_url(r["rtsp_main"])
        r["rtsp_sub"] = _mask_url(r["rtsp_sub"])
        out.append(r)
    return {"items": out, "total": len(out)}


@router.post("/sources")
def create_source(body: dict, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    # 社区版额度：全平台最多 MAX_CAMERAS 路视频通道
    from ..core import edition as _ed
    _n = db.query(Camera).filter(Camera.enabled == 1).count()
    if _ed.cameras_full(_n):
        raise HTTPException(403, _ed.cameras_message(_n))
    _need_edit(user)
    site = (body.get("site_id") or "").strip()
    if not site:
        raise HTTPException(400, "site_id 必填")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "名称必填")

    access = (body.get("access_type") or "rtsp").strip()
    if access != "rtsp":
        raise HTTPException(400, "当前只支持 rtsp 接入")
    rtsp_main = (body.get("rtsp_main") or "").strip()
    if access == "rtsp" and not rtsp_main:
        raise HTTPException(400, "RTSP 源必须填 rtsp_main（完整地址，含账号密码）")
    if rtsp_main and not rtsp_main.lower().startswith("rtsp://"):
        raise HTTPException(400, "rtsp_main 必须以 rtsp:// 开头")

    # 同一站点内序号唯一（流名就是按它生成的，重复会串台）
    # 只统计启用中的通道：软删的不能再占序号，否则新建通道流名会跳号（S001-2 而不是 S001-1）
    used = {c.sort_no for c in db.query(Camera)
              .filter(Camera.site_id == site, Camera.enabled == 1).all()}
    nxt = 0
    while nxt in used:
        nxt += 1

    # 编码是唯一键，但软删的记录还占着它 —— 自动避让而不是直接报错，
    # 否则删掉一条就再也不能用同名编码新建（现场会被这个卡住）
    base = (body.get("code") or f"{site}-CAM{nxt + 1:02d}").strip()
    code = base
    k = 1
    while db.query(Camera).filter(Camera.code == code).first():
        code = f"{base}-{k}"
        k += 1
        if k > 99:
            raise HTTPException(400, f"编码 {base} 及其后缀都已被占用")
    if body.get("code") and code != base:
        raise HTTPException(400, f"通道编码 {base} 已存在")

    cam = Camera(
        site_id=site, code=code, name=name,
        location=body.get("location"), brand=body.get("brand"),
        ip=body.get("ip"), rtsp_port=int(body.get("rtsp_port") or 554),
        access_type=access, rtsp_main=rtsp_main,
        rtsp_sub=(body.get("rtsp_sub") or "").strip() or None,
        sort_no=int(body.get("sort_no") if body.get("sort_no") is not None else nxt),
        wall_slot=int(body.get("wall_slot") or 0),
        record_enable=int(body.get("record_enable") or 1),
        keep_days=int(body.get("keep_days") or 30),
        enabled=1)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return {"ok": True, "id": cam.id, "stream": _stream_of(cam)}


@router.put("/sources/{cid}")
def update_source(cid: int, body: dict, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    _need_edit(user)
    cam = db.query(Camera).filter(Camera.id == cid).first()
    if not cam:
        raise HTTPException(404, "通道不存在")
    check_site_permission(user, cam.site_id, db)

    if "name" in body:
        n = (body.get("name") or "").strip()
        if not n:
            raise HTTPException(400, "名称不能为空")
        cam.name = n[:64]
    # 空字符串 / 带 ****** 的表示"没改"，只有真正给了新地址才写
    for k in ("rtsp_main", "rtsp_sub"):
        if k in body:
            v = (body.get(k) or "").strip()
            if "******" in v:
                continue
            if v and not v.lower().startswith("rtsp://"):
                raise HTTPException(400, f"{k} 必须以 rtsp:// 开头")
            setattr(cam, k, v or None)
    for k, lo, hi in (("sort_no", 0, 999), ("wall_slot", 0, 64),
                      ("rtsp_port", 1, 65535), ("keep_days", 1, 3650)):
        if k in body and body[k] is not None:
            try:
                v = int(body[k])
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} 必须是整数")
            if not (lo <= v <= hi):
                raise HTTPException(400, f"{k} 必须在 {lo}~{hi}")
            setattr(cam, k, v)
    for k in ("location", "brand", "ip"):
        if k in body:
            setattr(cam, k, body.get(k))
    for k in ("record_enable", "ptz", "enabled"):
        if k in body:
            setattr(cam, k, 1 if int(body[k] or 0) else 0)

    db.commit()
    return {"ok": True}


@router.delete("/sources/{cid}")
def delete_source(cid: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """软删（enabled=0），已排进监控墙的分屏位一并释放。"""
    _need_edit(user)
    cam = db.query(Camera).filter(Camera.id == cid).first()
    if not cam:
        raise HTTPException(404, "通道不存在")
    check_site_permission(user, cam.site_id, db)
    cam.enabled = 0
    cam.wall_slot = 0
    db.commit()
    return {"ok": True}


# ===================== 通道树 =====================
@router.get("/tree")
def channel_tree(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按站点分组返回启用中的通道，给「监控墙 / 通道选择」用。"""
    rows = (db.query(Camera).filter(Camera.enabled == 1)
              .order_by(Camera.site_id, Camera.sort_no, Camera.id).all())
    tree = {}
    for c in rows:
        st = tree.setdefault(c.site_id, {"site_id": c.site_id, "channels": []})
        st["channels"].append({
            "id": c.id, "code": c.code, "name": c.name, "ch": (c.sort_no or 0) + 1,
            "stream": _stream_of(c), "access_type": c.access_type or "rtsp",
            "online": bool(c.status), "wall_slot": c.wall_slot or 0,
        })
    return {"sites": list(tree.values())}


# ===================== RTSP 探测 =====================
async def _probe_rtsp(url: str, timeout: float = 20.0) -> dict:
    """让 ZLM 临时拉一路流，读 getMediaInfo，然后立刻删掉。

    为什么不本机 ffprobe：backend 容器没有 ffmpeg；ZLM 容器有，而且拉流成功后
    getMediaInfo 拿到的就是真实解码参数（编码/分辨率/帧率/码率）。
    """
    stream = "_probe_" + uuid.uuid4().hex[:10]
    c = await zlm_client()
    key = None
    try:
        r = await c.get(ZLM + "/index/api/addStreamProxy", params={
            "vhost": VHOST, "app": APP, "stream": stream, "url": url,
            "enable_hls": 0, "enable_mp4": 0, "enable_rtsp": 1,
            "enable_rtmp": 0, "enable_ts": 0, "enable_fmp4": 0,
            "rtp_type": 0,
        })
        d = r.json()
        if d.get("code") != 0:
            return {"ok": False, "error": d.get("msg") or "ZLM 拒绝拉流（地址/账号/网络不通）"}
        key = (d.get("data") or {}).get("key")

        deadline = asyncio.get_event_loop().time() + timeout
        last = {}
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.0)
            info = await c.get(ZLM + "/index/api/getMediaInfo",
                               params={"schema": "rtsp", "vhost": VHOST,
                                       "app": APP, "stream": stream})
            j = info.json()
            last = j
            tracks = j.get("tracks") or []
            if tracks:
                # 一定要挑**视频轨**：海康这类设备是先音频后视频，
                # 取 tracks[0] 会拿到 AAC，分辨率就全是 null
                vid = next((t for t in tracks
                            if t.get("codec_id") in (0, 1) or t.get("codec_type") == 0), None)
                v = vid or tracks[0]
                codec = {0: "H264", 1: "H265", 2: "AAC", 3: "G711A", 4: "G711U"}.get(
                    v.get("codec_id"), str(v.get("codec_id")))
                return {
                    "ok": True, "codec": codec,
                    "width": v.get("width"), "height": v.get("height"),
                    "fps": v.get("fps"), "bitrate_kbps": round((v.get("bit_rate") or 0) / 1024),
                    "audio": any(t.get("codec_id") in (2, 3, 4) for t in tracks),
                    "tracks": len(tracks),
                    "browser_ok": codec == "H264",   # H.265 浏览器播不了，要 ZLM 转码
                }
        return {"ok": False, "error": "拉流超时：地址能连但拿不到视频轨（可能是 H.265 或需要鉴权）",
                "zlm": last}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if key:
            try:
                await c.get(ZLM + "/index/api/delStreamProxy", params={"key": key})
            except Exception:
                pass
        await c.aclose()


@router.post("/probe")
async def probe(body: dict, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """探测 RTSP：{url:"rtsp://..."} 或 {id:通道id}。返回编码/分辨率/帧率/码率。"""
    url = (body.get("url") or "").strip()
    cid = body.get("id")
    if not url and cid:
        cam = db.query(Camera).filter(Camera.id == int(cid)).first()
        if not cam:
            raise HTTPException(404, "通道不存在")
        check_site_permission(user, cam.site_id, db)
        url = cam.rtsp_main
    if not url:
        raise HTTPException(400, "需要 url 或 id")
    if not url.lower().startswith("rtsp://"):
        raise HTTPException(400, "只支持 rtsp:// 地址")
    return await _probe_rtsp(url)


# ===================== 拉流 / 停流 =====================
def _resolve_stream(db, body):
    """从 {id} 或 {site, ch} 得到 (camera, stream, rtsp_url)。

    body["sub"] = True 时用子码流。子码流没配地址就回落主码流，
    并在返回值第 4 项标记 fellback_main=True，调用方可据此提示用户。
    """
    want_sub = bool(body.get("sub"))
    cid = body.get("id")
    if cid:
        cam = db.query(Camera).filter(Camera.id == int(cid)).first()
        if not cam:
            raise HTTPException(404, "通道不存在")
        return _pick_stream(cam, want_sub)
    site = (body.get("site") or "").strip()
    ch = int(body.get("ch") or 1)
    if not site:
        raise HTTPException(400, "需要 id 或 site+ch")
    cams = (db.query(Camera).filter(Camera.site_id == site, Camera.enabled == 1)
              .order_by(Camera.sort_no, Camera.id).all())
    if ch < 1 or ch > len(cams):
        raise HTTPException(404, f"站点 {site} 没有第 {ch} 路")
    return _pick_stream(cams[ch - 1], want_sub)


def _pick_stream(cam, want_sub):
    """按主/辅码流取 (camera, stream, rtsp_url, fellback_main)。"""
    if want_sub and cam.rtsp_sub:
        return cam, _stream_of(cam, sub=True), cam.rtsp_sub, False
    if not cam.rtsp_main:
        if cam.rtsp_sub:
            return cam, _stream_of(cam, sub=True), cam.rtsp_sub, False
        raise HTTPException(400, "该通道主/子码流都没有配置 RTSP 地址")
    # 要子码流但没配 → 回落主码流，明确告诉调用方
    return cam, _stream_of(cam), cam.rtsp_main, bool(want_sub)


@router.post("/live/start")
async def live_start(body: dict, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """按需拉流（幂等：已经在拉就直接返回在线）。"""
    cam, stream, url, fellback = _resolve_stream(db, body)
    check_site_permission(user, cam.site_id, db)
    c = await zlm_client()
    try:
        info = await c.get(ZLM + "/index/api/getMediaList",
                           params={"vhost": VHOST, "app": APP, "stream": stream})
        if (info.json().get("data") or []):
            return {"ok": True, "stream": stream, "already": True}
        r = await c.get(ZLM + "/index/api/addStreamProxy", params={
            "vhost": VHOST, "app": APP, "stream": stream, "url": url,
            "enable_hls": 1, "enable_mp4": 0, "enable_rtsp": 1,
            "enable_rtmp": 1, "enable_ts": 1, "enable_fmp4": 1, "rtp_type": 0,
        })
        d = r.json()
        if d.get("code") != 0:
            raise HTTPException(502, f"拉流失败：{d.get('msg') or d}")
        return {"ok": True, "stream": stream,
                "key": (d.get("data") or {}).get("key"), "already": False}
    finally:
        await c.aclose()


@router.post("/live/stop")
async def live_stop(body: dict, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """停止拉流（释放带宽）。找不到代理也返回 ok（幂等）。"""
    cam, stream, _, _ = _resolve_stream(db, body)
    check_site_permission(user, cam.site_id, db)
    c = await zlm_client()
    try:
        lst = await c.get(ZLM + "/index/api/getMediaList", params={"vhost": VHOST, "app": APP})
        keys = []
        for s in (lst.json().get("data") or []):
            if s.get("stream") == stream:
                keys.append(s.get("key") or s.get("originUrl"))
        for k in keys:
            if k:
                await c.get(ZLM + "/index/api/delStreamProxy", params={"key": k})
        # 兜底：按流名删（有些版本 getMediaList 不返回 key）
        await c.get(ZLM + "/index/api/close_streams",
                    params={"vhost": VHOST, "app": APP, "stream": stream, "force": 1})
        return {"ok": True, "stream": stream, "closed": len(keys)}
    finally:
        await c.aclose()


@router.get("/live/status")
async def live_status(id: int = None, site: str = None, ch: int = 1,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    cam, stream, _, _ = _resolve_stream(db, {"id": id, "site": site, "ch": ch})
    check_site_permission(user, cam.site_id, db)
    c = await zlm_client()
    try:
        lst = await c.get(ZLM + "/index/api/getMediaList", params={"vhost": VHOST, "app": APP})
        hit = next((s for s in (lst.json().get("data") or []) if s.get("stream") == stream), None)
        if not hit:
            return {"online": False, "stream": stream}
        tracks = hit.get("tracks") or []
        # 同样要挑视频轨（设备常把音频排在前面）
        v = next((t for t in tracks
                  if t.get("codec_id") in (0, 1) or t.get("codec_type") == 0), None) or {}
        return {"online": True, "stream": stream,
                "readers": hit.get("totalReaderCount"),
                "codec": {0: "H264", 1: "H265"}.get(v.get("codec_id"), v.get("codec_id")),
                "width": v.get("width"), "height": v.get("height"),
                "fps": v.get("fps")}
    finally:
        await c.aclose()


# ===================== 回放（NVR 的 RTSP 回放） =====================
def _playback_url(cam, start: str, end: str, sub: bool = False) -> str:
    """按品牌拼 NVR 回放地址。start/end 形如 2026-11-10 10:00:00。

    大华：/cam/playback?channel=N&subtype=0&starttime=2026-11-10T10:00:00&endtime=...
    海康：/Streaming/tracks/N01?starttime=20261110T100000Z&endtime=...
    其它：原样返回主码流地址（多数国产 NVR 兼容大华格式，先给一个能试的）
    """
    import urllib.parse as up

    def _cred(u):
        if not u:
            return ""
        try:
            p = up.urlsplit(u)
            return f"{p.username}:{p.password}@" if p.username else ""
        except Exception:
            return ""

    t0 = start.replace(" ", "T")
    t1 = end.replace(" ", "T")
    hk0 = start.replace(" ", "T").replace("-", "").replace(":", "") + "Z"
    hk1 = end.replace(" ", "T").replace("-", "").replace(":", "") + "Z"
    host = cam.ip or ""
    port = cam.rtsp_port or 554
    cred = _cred(cam.rtsp_main)
    brand = (cam.brand or "").lower()
    n = (cam.sort_no or 0) + 1

    if "hik" in brand:
        ch = f"{n}01"
        return f"rtsp://{cred}{host}:{port}/Streaming/tracks/{ch}?starttime={hk0}&endtime={hk1}"
    if "dahua" in brand or not brand:
        return (f"rtsp://{cred}{host}:{port}/cam/playback?channel={n}&subtype={1 if sub else 0}"
                f"&starttime={t0}&endtime={t1}")
    # 未知品牌：退回大华格式（兼容面最广）
    return (f"rtsp://{cred}{host}:{port}/cam/playback?channel={n}&subtype=0"
            f"&starttime={t0}&endtime={t1}")


@router.get("/playback")
async def playback_info(cid: int, start: str, end: str, sub: bool = False,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """返回 NVR 回放流地址（ZLM 拉流后给浏览器播）。

    注意：这不是「真正的拖拽回放」——拖动进度条 = 重新按新时间段拉一路流，
    会有 2~5 秒黑屏，这是 RTSP 回放的物理特性（NVR 不支持随机寻址）。
    """
    cam = db.query(Camera).filter(Camera.id == cid).first()
    if not cam:
        raise HTTPException(404, "通道不存在")
    check_site_permission(user, cam.site_id, db)
    if not cam.rtsp_main:
        raise HTTPException(400, "该通道没有配置 rtsp_main，无法生成回放地址")
    try:
        datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(400, "时间格式必须是 YYYY-MM-DD HH:MM:SS")

    url = _playback_url(cam, start, end, sub)
    stream = f"{_stream_of(cam)}_pb"
    c = await zlm_client()
    try:
        await c.get(ZLM + "/index/api/delStreamProxy", params={"key": f"{VHOST}/{APP}/{stream}"})
        r = await c.get(ZLM + "/index/api/addStreamProxy", params={
            "vhost": VHOST, "app": APP, "stream": stream, "url": url,
            "enable_hls": 0, "enable_mp4": 0, "enable_rtsp": 1,
            "enable_rtmp": 1, "enable_ts": 1, "enable_fmp4": 0, "rtp_type": 0,
        })
        d = r.json()
        if d.get("code") != 0:
            raise HTTPException(502, f"NVR 回放拉流失败：{d.get('msg') or d}")
        from .zlm_hook import sign
        tok = sign(stream)
        return {"ok": True, "stream": stream, "rtsp": url,
                "play_url": f"/live/{stream}.live.flv?token={tok['token']}",
                "token": tok["token"], "exp": tok["exp"],
                "note": "拖动进度条会重新拉流，黑屏 2~5 秒属正常"}
    finally:
        await c.aclose()


