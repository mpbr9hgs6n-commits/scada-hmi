# -*- coding: utf-8 -*-
"""数据库备份（第 04 章）。

范围刻意收窄：
  - MySQL：mysqldump 生成文件 + 页面下载 + 滚动保留 3 份
  - TDengine：只在页面显示状态（库大小/最早数据/当前 KEEP/上次备份），**不下载**
    理由：20 万点位规模下 taosdump 出来可能几十 GB，浏览器下载不现实

安全要点：
  - 备份前检查磁盘剩余（< 10GB 直接拒绝），避免把盘写满让平台整体挂掉
  - mysqldump 用 --single-transaction（不锁表），密码走 MYSQL_PWD 环境变量
    （写成 -pPASSWORD 会在 ps aux 里明文可见）
  - 不提供"还原"接口，还原上服务器人工做
"""
import datetime as dt
import os
import re
import shutil
import subprocess

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db, td_query, td_url_for_site
from ..models import User, Site
from ..auth import get_current_user
from .history import _rows_of

router = APIRouter(prefix="/api", tags=["backup"])

BACKUP_DIR = os.getenv("BACKUP_DIR", "/data/backup")
KEEP_FILES = 3                      # 只留 3 份
MIN_FREE_BYTES = 10 * 1024 ** 3     # 低于 10GB 拒绝备份

_NAME_RE = re.compile(r"^plant_\d{8}_\d{6}\.sql$")


def _require_admin(user: User):
    if (user.role_code or "") != "admin":
        raise HTTPException(403, "只有管理员能操作备份")


def _db_conf():
    """从环境读 MySQL 连接信息（与后端同一个库）。"""
    return {
        "host": os.getenv("MYSQL_HOST", "mysql"),
        "port": os.getenv("MYSQL_PORT", "3306"),
        "user": os.getenv("MYSQL_USER", "root"),
        # 项目 .env 里的变量名是 MYSQL_ROOT_PWD（不是 MYSQL_PASSWORD）
        "password": os.getenv("MYSQL_ROOT_PWD") or os.getenv("MYSQL_PASSWORD", ""),
        "db": os.getenv("MYSQL_DB", "plant"),
    }


def _ensure_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR


def _list_files():
    d = _ensure_dir()
    out = []
    for fn in sorted(os.listdir(d), reverse=True):
        if not _NAME_RE.match(fn):
            continue
        fp = os.path.join(d, fn)
        try:
            st = os.stat(fp)
        except OSError:
            continue
        out.append({"name": fn, "size": st.st_size,
                    "mtime": dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
    return out


def _prune():
    """滚动保留：留下最新 KEEP_FILES 份，其余删除。"""
    files = _list_files()
    for f in files[KEEP_FILES:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, f["name"]))
        except OSError:
            pass
    return [f["name"] for f in files[KEEP_FILES:]]


@router.post("/backup/create")
def backup_create(user: User = Depends(get_current_user)):
    """执行一次 MySQL 备份。先查磁盘，再 dump，最后滚动删除。"""
    _require_admin(user)
    d = _ensure_dir()

    usage = shutil.disk_usage(d)
    if usage.free < MIN_FREE_BYTES:
        raise HTTPException(400,
            f"磁盘剩余 {usage.free // 1024 ** 3} GB，低于 {MIN_FREE_BYTES // 1024 ** 3} GB，"
            f"已拒绝备份（避免写满磁盘导致平台不可用）")

    conf = _db_conf()
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = f"plant_{ts}.sql"
    fp = os.path.join(d, fn)

    cmd = [
        "mysqldump",
        f"-h{conf['host']}", f"-P{conf['port']}", f"-u{conf['user']}",
        "--single-transaction", "--routines", "--triggers",
        "--default-character-set=utf8mb4",
        conf["db"],
    ]
    env = dict(os.environ)
    env["MYSQL_PWD"] = conf["password"]        # 密码走环境变量，不进命令行

    t0 = dt.datetime.now()
    try:
        with open(fp, "wb") as fh:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env=env, timeout=1800)
    except subprocess.TimeoutExpired:
        if os.path.exists(fp):
            os.remove(fp)
        raise HTTPException(500, "备份超时（30 分钟），已删除半成品文件")
    except FileNotFoundError:
        raise HTTPException(500, "容器里没有 mysqldump 命令")

    if r.returncode != 0:
        if os.path.exists(fp):
            os.remove(fp)
        raise HTTPException(500, "备份失败：" + (r.stderr or b"").decode("utf-8", "replace")[:300])

    size = os.path.getsize(fp)
    if size < 1024:
        os.remove(fp)
        raise HTTPException(500, f"备份文件只有 {size} 字节，明显不对，已删除")

    removed = _prune()
    return {
        "ok": True, "name": fn, "size": size,
        "ms": int((dt.datetime.now() - t0).total_seconds() * 1000),
        "removed": removed,
        "disk_free_gb": usage.free // 1024 ** 3,
    }


@router.get("/backup/list")
def backup_list(user: User = Depends(get_current_user)):
    _require_admin(user)
    d = _ensure_dir()
    u = shutil.disk_usage(d)
    return {"ok": True, "dir": d, "keep": KEEP_FILES,
            "disk_free_gb": u.free // 1024 ** 3, "disk_total_gb": u.total // 1024 ** 3,
            "files": _list_files()}


@router.get("/backup/download")
def backup_download(name: str, user: User = Depends(get_current_user)):
    _require_admin(user)
    if not _NAME_RE.match(name or ""):
        raise HTTPException(400, "文件名不合法")
    fp = os.path.join(BACKUP_DIR, name)
    if not os.path.isfile(fp):
        raise HTTPException(404, "文件不存在")
    return FileResponse(fp, media_type="application/octet-stream", filename=name)


@router.get("/backup/status")
async def backup_status(db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """MySQL 备份状态 + TDengine 四项（库大小/最早数据/KEEP/上次备份时间）。"""
    _require_admin(user)
    files = _list_files()
    last = files[0] if files else None

    # TDengine：用第一个站点的库地址（所有站点共用同一实例时结果一致）
    earliest = None
    keep_days = None
    db_note = ""
    site = db.query(Site).order_by(Site.id).first()
    if site:
        try:
            td_url = td_url_for_site(db, site.id)
            # TDengine REST 的 data 是"数组的数组"，必须用 column_meta 映射成 dict，
            # 不能直接 .get()（那会 AttributeError: 'list' object has no attribute 'get'）
            # 只取最早时间：count(*) 在 TDengine 上是全表扫描，20 万点位会拖到
            # 几十秒，而这里根本不需要行数（会导致 /api/backup/status 请求挂起）
            d1 = _rows_of(await td_query(
                "select first(ts) as f from plant.samples", td_url))
            if d1:
                earliest = d1[0].get("f")
            d2 = _rows_of(await td_query("show databases", td_url))
            for r in d2:
                if str(r.get("name") or "").lower() == "plant":
                    keep_days = r.get("keep")
                    break
        except Exception as e:
            db_note = str(e)[:160]

    days_used = None
    if earliest:
        try:
            s = str(earliest).replace("T", " ")[:19]
            t0 = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            days_used = (dt.datetime.now() - t0).days
        except Exception:
            pass

    return {
        "ok": True,
        "mysql": {"last_name": last["name"] if last else None,
                  "last_time": last["mtime"] if last else None,
                  "last_size": last["size"] if last else None,
                  "keep": KEEP_FILES,
                  "disk_free_gb": shutil.disk_usage(_ensure_dir()).free // 1024 ** 3},
        "tdengine": {"earliest": str(earliest) if earliest else None,
                     "keep_days": keep_days,
                     "days_used": days_used,
                     "note": db_note,
                     "backup_supported": False,
                     "why": "20 万点位规模下 taosdump 可能几十 GB，不在页面提供下载"},
    }
