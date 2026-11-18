# -*- coding: utf-8 -*-
"""数据保留期（第 03 章）。

TDengine 的 KEEP 是**数据库级**参数，不是表级也不是点位级：
    ALTER DATABASE plant KEEP <天数>
超期数据由 TDengine 按文件块异步回收，不需要（也不允许）自己写"按点位 DELETE"。

配置落在现成的 sys_config 表：
    history.keep_days    历史数据保留天数（已有，默认 365）
    history.alert_days   到期前多少天开始提醒备份（本章新增，默认 7）
"""
import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, td_query, td_exec, td_url_for_site
from ..models import User, Site, SysConfig
from ..auth import get_current_user
from .history import _rows_of

router = APIRouter(prefix="/api", tags=["system"])

CFG_KEEP = "history.keep_days"
CFG_ALERT = "history.alert_days"
KEEP_MIN, KEEP_MAX = 1, 3650        # 1 天 ~ 10 年
ALERT_MIN, ALERT_MAX = 0, 365


def _require_admin(user: User):
    if (user.role_code or "") != "admin":
        raise HTTPException(403, "只有管理员能修改数据保留策略")


def _cfg_get(db: Session, key: str, default: str = "") -> str:
    r = db.query(SysConfig).filter(SysConfig.key == key).first()
    return (r.value if r and r.value is not None else default)


def _cfg_set(db: Session, key: str, value: str, descr: str = None):
    r = db.query(SysConfig).filter(SysConfig.key == key).first()
    if r:
        r.value = str(value)
        if descr:
            r.descr = descr
    else:
        db.add(SysConfig(key=key, value=str(value), descr=descr or ""))
    db.commit()


def _int_cfg(db: Session, key: str, default: int, lo: int, hi: int) -> int:
    raw = _cfg_get(db, key, str(default))
    try:
        v = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _td_url(db: Session) -> str:
    s = db.query(Site).order_by(Site.id).first()
    return td_url_for_site(db, s.id if s else None)


async def _td_keep_days(db: Session):
    """读 TDengine 当前 KEEP（天）。读不到返回 None。

    注意两点（都实测过）：
    1. `SHOW DATABASES` 在 3.3.5 上只返回 name 一列，没有 keep；
       必须查 information_schema.ins_databases。
    2. 该表的 keep 是 "180d,180d,180d" 这种三级存储的复合字符串
       （KEEP / DURATION 等），要取第一个数字。
    """
    try:
        rows = _rows_of(await td_query(
            "select name, `keep` from information_schema.ins_databases where name='plant'",
            _td_url(db)))
        for r in rows:
            v = str(r.get("keep") or "")
            m = re.match(r"\s*(\d+)", v)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


async def _td_earliest(db: Session):
    """读 TDengine 最早一条数据的时间。没数据返回 None。

    只取 first(ts)：count(*) 在 TDengine 上是全表扫描，20 万点位会拖几十秒，
    而这个接口只是给设置页显示状态用，不需要行数。
    """
    try:
        rows = _rows_of(await td_query("select first(ts) as f from plant.samples", _td_url(db)))
        if rows:
            return rows[0].get("f")
    except Exception:
        pass
    return None


@router.get("/system/retention")
async def get_retention(db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """读当前保留策略 + 库里实际状态。"""
    _require_admin(user)
    keep_days = _int_cfg(db, CFG_KEEP, 365, KEEP_MIN, KEEP_MAX)
    alert_days = _int_cfg(db, CFG_ALERT, 7, ALERT_MIN, ALERT_MAX)

    earliest = await _td_earliest(db)
    td_keep = await _td_keep_days(db)

    days_used = None
    days_left = None
    if earliest:
        try:
            s = str(earliest).replace("T", " ")[:19]
            t0 = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            days_used = (dt.datetime.now() - t0).days
            days_left = keep_days - days_used
        except Exception:
            pass

    return {
        "ok": True,
        "config": {"keep_days": keep_days, "alert_days": alert_days,
                   "range": {"keep": [KEEP_MIN, KEEP_MAX], "alert": [ALERT_MIN, ALERT_MAX]}},
        "actual": {"tdengine_keep_days": td_keep, "earliest": str(earliest) if earliest else None,
                   "days_used": days_used, "days_left": days_left},
        "notice": (f"数据库将在 {days_left} 天后清理 {days_used} 天前的历史数据，请先备份。"
                   if days_left is not None and days_left <= alert_days else ""),
    }


@router.put("/system/retention")
async def set_retention(body: dict,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """改保留天数：写 sys_config + 执行 ALTER DATABASE KEEP。

    执行前记下当前 keep，失败时返回错误原文（不在后台偷偷改）。
    """
    _require_admin(user)
    if "keep_days" not in body:
        raise HTTPException(400, "keep_days 必填")
    try:
        keep_days = int(float(str(body.get("keep_days")).strip()))
    except (TypeError, ValueError):
        raise HTTPException(400, "keep_days 必须是整数（天）")
    if keep_days < KEEP_MIN or keep_days > KEEP_MAX:
        raise HTTPException(400, f"保留天数必须在 {KEEP_MIN}~{KEEP_MAX} 之间")

    alert_days = None
    if "alert_days" in body and body.get("alert_days") not in (None, ""):
        try:
            alert_days = int(float(str(body.get("alert_days")).strip()))
        except (TypeError, ValueError):
            raise HTTPException(400, "alert_days 必须是整数（天）")
        if alert_days < ALERT_MIN or alert_days > ALERT_MAX:
            raise HTTPException(400, f"提前提醒天数必须在 {ALERT_MIN}~{ALERT_MAX} 之间")

    before = await _td_keep_days(db)
    sql = f"alter database plant keep {keep_days}"
    try:
        r = await td_exec(sql, _td_url(db))
        if isinstance(r, dict) and r.get("code") not in (0, None):
            raise RuntimeError(f"TDengine error {r.get('code')}: {r.get('desc')}")
    except Exception as e:
        raise HTTPException(500, f"执行 ALTER DATABASE 失败（当前 keep={before}）：{str(e)[:240]}")

    _cfg_set(db, CFG_KEEP, str(keep_days), "历史数据保留天数")
    if alert_days is not None:
        _cfg_set(db, CFG_ALERT, str(alert_days), "到期前提醒备份的天数")

    after = await _td_keep_days(db)
    return {"ok": True, "sql": sql, "keep_before": before, "keep_after": after,
            "keep_days": keep_days,
            "alert_days": alert_days if alert_days is not None else _int_cfg(db, CFG_ALERT, 7, ALERT_MIN, ALERT_MAX)}


@router.get("/system/storage")
async def storage_status(db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """给全局提醒用：当前保留期 / 最早数据 / 是否该提醒备份。"""
    keep_days = _int_cfg(db, CFG_KEEP, 365, KEEP_MIN, KEEP_MAX)
    alert_days = _int_cfg(db, CFG_ALERT, 7, ALERT_MIN, ALERT_MAX)
    earliest = await _td_earliest(db)
    days_used = None
    days_left = None
    if earliest:
        try:
            s = str(earliest).replace("T", " ")[:19]
            t0 = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            days_used = (dt.datetime.now() - t0).days
            days_left = keep_days - days_used
        except Exception:
            pass
    # 从来没数据（earliest is None）时不算到期，不弹窗
    need_alert = bool(days_left is not None and days_left <= alert_days)
    return {
        "ok": True, "keep_days": keep_days, "alert_days": alert_days,
        "earliest": str(earliest) if earliest else None,
        "days_used": days_used, "days_left": days_left,
        "need_alert": need_alert,
        "message": (f"数据库保留 {keep_days} 天，已用 {days_used} 天，"
                    f"还有 {days_left} 天到期。到期后 {days_used} 天前的数据将被自动清理，请先备份。"
                    if need_alert else ""),
    }
