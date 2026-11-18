"""视频：流地址 / 相机清单 / 拉流代理（P1-6）
   相机清单从环境变量 VIDEO_CAMERAS 读，格式：
   {"S001":[{"name":"进水口","rtsp":"rtsp://your_user:your_password@192.168.1.60:554/cam/realmonitor?channel=1&subtype=0"}],
    "S002":[...]}
   浏览器统一用 flv.js 播 /live/{stream}.live.flv（nginx 同源反代到 ZLM）
"""
import asyncio
import json
import logging
import os

log = logging.getLogger("video")

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Camera, User
from ..auth import get_current_user, check_site_permission
from ..core.zlm import zlm_get
from .zlm_hook import sign

router = APIRouter(prefix="/api/video", tags=["video"])


# 拉流互斥锁：多个浏览器/多次刷新会并发调 /cameras，不加锁会对着同一路
# 反复 addStreamProxy，ZLM 里堆出一堆同名代理（实测堆了 5 份），最后把 NVR 连满
_PULL_LOCK = asyncio.Lock()
# 一次最多主动拉几路：NVR 并发 RTSP 有上限，全拉会大面积超时。
# 组态视频窗只显示当前站的一路，拉 2 路足够（第 2 路给切换留余量）。
PULL_LIMIT = int(os.getenv("VIDEO_PULL_LIMIT", "8"))   # 每站主+辅最多 2N 路，2 太小


def _cameras():
    try:
        return json.loads(os.getenv("VIDEO_CAMERAS", "{}") or "{}")
    except Exception:
        return {}


def _stream_name(site: str, idx: int) -> str:
    return f"{site}-{idx + 1}"


async def _online(stream: str):
    """用 getMediaList 判断（新版 isMediaOnline 强制要 schema 参数，容易误判离线）"""
    try:
        d = await zlm_get("/index/api/getMediaList")
        for s in d.get("data") or []:
            if s.get("app") == "live" and s.get("stream") == stream:
                return True
        return False
    except Exception:
        return False


async def _pull(stream: str, rtsp: str):
    """让 ZLM 拉相机 RTSP（H.265 自动转码为 H.264，浏览器才播得了）

    注意：zlm_client() 返回的是**裸 client，没有 base_url**，必须自己拼完整地址。
    这里以前写成 c.get("/index/api/...") 会抛 ValueError: unknown url type，
    而因为 VIDEO_CAMERAS 一直是空的、从没走到这条分支，这个 bug 一直没暴露。
    """
    from .. import config
    from ..core.zlm import zlm_client
    c = await zlm_client()
    try:
        # 先查代理：addStreamProxy 是"建代理"，不是"确保存在"。
        # 代理建好后一直在（listStreamProxy 里有），但流只在有人看时才存在
        # （getMediaList 会空）。只查 getMediaList 就会误判"没拉过"，
        # 于是同一个流名被反复建代理 —— 实测最多堆到 60 个同名代理，
        # 播放时命中哪个不确定，表现为"选的是 A 路，播出来是 B 路"。
        try:
            lp = await c.get(config.ZLM_URL + "/index/api/listStreamProxy",
                             params={"vhost": "__defaultVhost__", "app": "live"})
            for it in ((lp.json() or {}).get("data") or []):
                # 流名不在顶层 stream：在 key（__defaultVhost__/live/xxx）或 src.stream 里
                nm = ((it.get("src") or {}).get("stream")
                      or str(it.get("key") or "").rsplit("/", 1)[-1])
                if nm == stream:
                    return {"code": 0, "existed": True, "key": it.get("key")}
        except Exception:
            pass
        r = await c.get(config.ZLM_URL + "/index/api/addStreamProxy", params={
            "vhost": "__defaultVhost__", "app": "live", "stream": stream,
            "url": rtsp, "enable_hls": 1, "enable_mp4": 0,
            "rtp_type": 0,
            "enable_rtsp": 1, "enable_rtmp": 1, "enable_ts": 1, "enable_fmp4": 1,
        })
        return r.json()
    finally:
        await c.aclose()


@router.get("/cameras")
async def cameras(site: str = "", db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """站点相机清单：带在线状态，未在线的自动触发拉流

    数据源优先级：camera 表（界面里维护的通道） > VIDEO_CAMERAS 环境变量 > 演示流。
    组态视频控件按列表下标取通道，所以顺序固定按 sort_no, id。
    """
    if site:
        check_site_permission(user, site, db)
    out = []

    # ① 优先用数据库里的通道（/api/video/sources 维护的那批）
    if site:
        rows = (db.query(Camera).filter(Camera.site_id == site, Camera.enabled == 1)
                  .order_by(Camera.sort_no, Camera.id).all())
        pulled = 0
        # H.265 浏览器播不了，拉流名额优先给 H.264 的通道（codec 由 probe 写入库）
        rows = sorted(rows, key=lambda c: (0 if (c.codec or "").upper() != "H265" else 1,
                                           c.sort_no or 0))
        for cam in rows:
            # 流名必须和 video_sources._stream_of 保持一致（主键派生），
            # 否则组态里按新流名选的通道，在这里查不到、拉不起。
            stream = f"{cam.site_id}-{cam.id}"
            stream_sub = f"{stream}-sub"
            alive = await _online(stream)
            if not alive and cam.rtsp_main and pulled < PULL_LIMIT:
                async with _PULL_LOCK:
                    # 拿锁后再查一次：等锁期间别的请求可能已经把它拉起来了
                    alive = await _online(stream)
                    if not alive:
                        try:
                            await _pull(stream, cam.rtsp_main)
                            # addStreamProxy 只是"开始拉"，NVR 响应 + ZLM 建流要 1~3 秒。
                            # 立刻查会是 offline，组态视频窗拿到 url 就播会黑屏 —— 这里等它就绪。
                            for _ in range(8):
                                await asyncio.sleep(0.5)
                                alive = await _online(stream)
                                if alive:
                                    break
                            pulled += 1
                        except Exception as e:
                            log.warning("拉流失败 %s: %s", stream, e)
                            alive = False
            tok = sign(stream)
            tok_sub = sign(stream_sub)
            # 子码流也要拉：现场常见"主码流还是 H.265、子码流已改成 H.264"，
            # 不拉子码流，切了码流也是黑屏。
            alive_sub = await _online(stream_sub)
            if not alive_sub and cam.rtsp_sub and pulled < PULL_LIMIT:
                async with _PULL_LOCK:
                    alive_sub = await _online(stream_sub)
                    if not alive_sub:
                        try:
                            await _pull(stream_sub, cam.rtsp_sub)
                            for _ in range(8):
                                await asyncio.sleep(0.5)
                                alive_sub = await _online(stream_sub)
                                if alive_sub:
                                    break
                            pulled += 1
                        except Exception as e:
                            log.warning("拉子码流失败 %s: %s", stream_sub, e)
                            alive_sub = False
            out.append({"name": cam.name or stream, "stream": stream,
                        "stream_sub": stream_sub,
                        "legacy_stream": f"{cam.site_id}-{(cam.sort_no or 0) + 1}",
                        "url": f"/live/{stream}.live.flv?token={tok['token']}",
                        "url_sub": f"/live/{stream_sub}.live.flv?token={tok_sub['token']}",
                        "token": tok["token"], "exp": tok["exp"],
                        "online": alive, "online_sub": alive_sub, "kind": "camera", "id": cam.id,
                        "codec": cam.codec, "codec_sub": cam.codec_sub or "",
                        "resolution": cam.resolution,
                        "sort_no": cam.sort_no or 0,
                        # 浏览器只解 H.264；H.265 即使在线也播不了
                        "browser_ok": (cam.codec or "").upper() != "H265",
                        "browser_ok_sub": ((cam.codec_sub or "").upper() == "H264") if cam.codec_sub else None})

    # ② 回落环境变量（老配置）
    if not out:
        cams = _cameras().get(site, [])
        for i, cam in enumerate(cams):
            stream = _stream_name(site, i)
            alive = await _online(stream)
            if not alive and cam.get("rtsp"):
                try:
                    await _pull(stream, cam["rtsp"])
                    alive = await _online(stream)
                except Exception:
                    alive = False
            tok = sign(stream)
            out.append({"name": cam.get("name") or f"通道{i + 1}", "stream": stream,
                        "url": f"/live/{stream}.live.flv?token={tok['token']}",
                        "token": tok["token"], "exp": tok["exp"],
                        "online": alive, "kind": "camera"})

    # ③ 都没有才给演示流，并明确标注，不冒充现场画面
    if not out:
        tok = sign("mock1")
        out.append({"name": "演示流（SMPTE 测试卡，非现场画面）", "stream": "mock1",
                    "url": f"/live/mock1.live.flv?token={tok['token']}",
                    "token": tok["token"], "exp": tok["exp"],
                    "online": await _online("mock1"), "kind": "mock"})
    return {"site": site, "items": out}


@router.get("/token")
async def video_token(stream: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """给组态图里的视频控件单独签发播放 token（5 分钟有效）

    stream 形如 S001-1（主码流）/ S001-1_sub（辅码流）/ mock1（演示流）。
    带站点前缀的按站点权限校验，避免拿别人的站点号来签 token。
    """
    base = stream[:-4] if stream.endswith("_sub") else stream
    site = base.rsplit("-", 1)[0] if "-" in base else ""
    if site:
        check_site_permission(user, site, db)
    tok = sign(stream)
    return {"stream": stream, "token": tok["token"], "exp": tok["exp"],
            "url": f"/live/{stream}.live.flv?token={tok['token']}"}


@router.get("/url")
async def video_url(site: str, ch: int = 1, mode: str = "live",
                    stream_type: str = "main",
                    start: str = None, end: str = None,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """返回浏览器可播的流地址（走 nginx /live/ 同源反代）"""
    check_site_permission(user, site, db)
    stream = f"{site}-{ch}" + ("_sub" if stream_type == "sub" else "")
    if mode == "live":
        tok = sign(stream)
        return {"mode": "live", "url": f"/live/{stream}.live.flv?token={tok['token']}",
                "token": tok["token"], "exp": tok["exp"],
                "hls": f"/live/{stream}/hls.m3u8"}
    elif mode == "playback":
        if not start or not end:
            raise HTTPException(400, "回放需要 start/end 参数")
        data = await zlm_get("/index/api/getMp4RecordFile",
                             vhost="__defaultVhost__", app="live",
                             stream=stream, period=start[:10])
        return {"mode": "playback", "stream": stream, "start": start, "end": end,
                "zlm_resp": data}
    raise HTTPException(400, "mode 必须是 live/playback")


@router.post("/heartbeat")
async def heartbeat(body: dict, user: User = Depends(get_current_user)):
    """播放心跳：确认流在线（防回收断流兜底）"""
    stream = body.get("stream", "")
    if not stream:
        return {"ok": False}
    return {"ok": True, "alive": await _online(stream)}


@router.get("/channels")
async def channels(site: str = None, user: User = Depends(get_current_user)):
    """当前 ZLM 在线流列表"""
    data = await zlm_get("/index/api/getMediaList")
    streams = []
    for s in (data.get("data") or []):
        if s.get("schema") == "rtmp":
            streams.append({"app": s.get("app"), "stream": s.get("stream"),
                            "originType": s.get("originType")})
    return {"items": streams}
