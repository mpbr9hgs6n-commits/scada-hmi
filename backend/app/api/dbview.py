# -*- coding: utf-8 -*-
"""数据库只读查询（第 04 章）。

四类预置查询，**全部只读**，不提供自由 SQL 输入框：
    点位 / 报警 / 历史 / 操作日志

为什么不做自由 SQL：20 万点位的 `point` 表 + TDengine 超级表，
一条 `SELECT * FROM samples` 就足以把库打到无响应。只读 != 安全。

历史查询限制：一次 1 个点位 × 1 个时间区间，行数上限 5000。
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db, td_query, td_url_for_site
from ..models import User, Point, Alarm, OpLog
from ..auth import get_current_user, check_site_permission
from ..core.validate import require_site, require_point, require_int, td_str
# 复用 history 模块的 TDengine 行解析（column_meta → dict），不要各写一份
from .history import _rows_of

router = APIRouter(prefix="/api", tags=["dbview"])

VIEW_MAX_ROWS = 5000      # 历史查询硬上限
VIEW_PAGE_SIZE = 50       # 列表类每页条数硬上限（不允许"查全部"）

_BAD_KW = ("insert ", "update ", "delete ", "drop ", "alter ", "create ",
           "truncate ", "replace into", "grant ", "revoke ")


def assert_readonly(sql: str) -> str:
    """只读守卫：非 SELECT/SHOW/DESCRIBE 开头、或含写操作关键字的语句直接拒绝。

    不靠"记得别写 UPDATE"，靠代码拦。所有 td_query 调用前都要过这一层。
    """
    s = (sql or "").strip().lstrip("(").lower()
    if not (s.startswith("select") or s.startswith("show") or s.startswith("describe")):
        raise HTTPException(400, "只读接口：只允许 SELECT / SHOW / DESCRIBE")
    for kw in _BAD_KW:
        if kw in s:
            raise HTTPException(400, "只读接口：语句里不允许出现 " + kw.strip())
    return sql


def _page_args(page: str, size: str = None):
    """分页参数：页大小硬顶 VIEW_PAGE_SIZE，不许传大值绕过。"""
    p = require_int(page, 1, 100000, "page", default=1) or 1
    n = require_int(size, 1, VIEW_PAGE_SIZE, "size", default=VIEW_PAGE_SIZE) or VIEW_PAGE_SIZE
    n = min(n, VIEW_PAGE_SIZE)
    return p, n


# ============================================================================
# 1) 点位
# ============================================================================
@router.get("/dbview/points")
def dbview_points(site: str, keyword: str = "", page: str = "1", size: str = None,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """点位列表（只读）。必须指定站点，支持编码/名称模糊搜索。"""
    site = require_site(site)
    check_site_permission(user, site, db)
    p, n = _page_args(page, size)

    qy = db.query(Point).filter(Point.site_id == site)
    kw = (keyword or "").strip()
    if kw:
        like = "%" + kw + "%"
        qy = qy.filter((Point.code.like(like)) | (Point.name.like(like)) | (Point.addr.like(like)))
    total = qy.count()
    rows = (qy.order_by(Point.code).offset((p - 1) * n).limit(n).all())
    return {
        "ok": True, "total": total, "page": p, "size": n,
        "rows": [{
            "code": r.code, "name": r.name, "addr": r.addr, "dtype": r.dtype,
            "unit": r.unit, "rw": r.rw, "save_history": r.save_history,
            "hist_interval": r.hist_interval, "poll_ms": r.poll_ms,
            "enabled": r.enabled,
        } for r in rows],
    }


# ============================================================================
# 2) 报警
# ============================================================================
@router.get("/dbview/alarms")
def dbview_alarms(site: str, level: str = None, state: str = None,
                  page: str = "1", size: str = None,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """报警列表（只读）。按站点 + 可选级别/状态筛选。"""
    site = require_site(site)
    check_site_permission(user, site, db)
    p, n = _page_args(page, size)

    qy = db.query(Alarm).filter(Alarm.site_id == site)
    lv = require_int(level, 1, 4, "level") if level not in (None, "") else None
    st = require_int(state, 0, 3, "state") if state not in (None, "") else None
    if lv is not None:
        qy = qy.filter(Alarm.level == lv)
    if st is not None:
        qy = qy.filter(Alarm.state == st)
    total = qy.count()
    rows = (qy.order_by(Alarm.first_ts.desc()).offset((p - 1) * n).limit(n).all())
    # Alarm 表没有 name 字段，点位名称从 point 表批量补（一次查询，不要逐行查）
    codes = list({r.point_code for r in rows if r.point_code})
    nmap = {}
    if codes:
        for pt in db.query(Point).filter(Point.site_id == site, Point.code.in_(codes)).all():
            nmap[pt.code] = pt.name or ""
    return {
        "ok": True, "total": total, "page": p, "size": n,
        "rows": [{
            "id": r.id, "point_code": r.point_code,
            "name": nmap.get(r.point_code, ""),
            "level": r.level, "state": r.state, "msg": r.msg,
            "val": r.val, "threshold": r.threshold,
            "first_ts": str(r.first_ts or ""), "last_ts": str(r.last_ts or ""),
            "count": r.count,
        } for r in rows],
    }


# ============================================================================
# 3) 历史（限量查：1 点位 × 1 区间 × 5000 行）
# ============================================================================
@router.get("/dbview/history")
async def dbview_history(site: str, point: str, from_ts: str, to_ts: str,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """历史数据（只读）。必须同时给站点/点位/起止时间，行数硬顶 5000。

    时间参数必须是 ISO 字符串（如 2026-11-14T00:00:00）：
    后端 require_ts 用 dt.datetime.fromisoformat，传 Unix 时间戳会 400。
    """
    site = require_site(site)
    point = require_point(point)
    check_site_permission(user, site, db)

    def _ts(v, name):
        try:
            return dt.datetime.fromisoformat(str(v))
        except Exception:
            raise HTTPException(400, f"{name} 必须是 ISO 时间，如 2026-11-07T12:00:00")

    f = _ts(from_ts, "from_ts")
    t = _ts(to_ts, "to_ts")
    if f > t:
        raise HTTPException(400, "from_ts 不能晚于 to_ts")

    td_url = td_url_for_site(db, site)
    where = (f"site={td_str(site)} and point={td_str(point)} "
             f"and ts >= {td_str(f.strftime('%Y-%m-%d %H:%M:%S'))} "
             f"and ts <= {td_str(t.strftime('%Y-%m-%d %H:%M:%S'))}")

    cnt_sql = assert_readonly(f"select count(*) as n from plant.samples where {where}")
    try:
        cd = await td_query(cnt_sql, td_url)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    total = 0
    cr = _rows_of(cd)
    if cr:
        try:
            total = int(cr[0].get("n") or 0)
        except (TypeError, ValueError):
            total = 0

    sql = assert_readonly(
        f"select to_char(ts,'yyyy-mm-dd hh24:mi:ss') as ts, val, q "
        f"from plant.samples where {where} order by ts desc limit {VIEW_MAX_ROWS}")
    try:
        data = await td_query(sql, td_url)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    rows = _rows_of(data)

    return {
        "ok": True, "total": total, "returned": len(rows),
        "capped": total > VIEW_MAX_ROWS, "limit": VIEW_MAX_ROWS,
        "note": (f"该区间共 {total} 条，已返回最新 {VIEW_MAX_ROWS} 条，请缩小时间范围"
                 if total > VIEW_MAX_ROWS else ""),
        "rows": rows,
    }


# ============================================================================
# 4) 操作日志
# ============================================================================
@router.get("/dbview/logs")
def dbview_logs(user: str = None, action: str = None,
                page: str = "1", size: str = None,
                db: Session = Depends(get_db),
                cur: User = Depends(get_current_user)):
    """操作日志（只读）。仅 admin 可见。"""
    if (cur.role_code or "") != "admin":
        raise HTTPException(403, "只有管理员能查看操作日志")
    p, n = _page_args(page, size)

    qy = db.query(OpLog)
    if user:
        qy = qy.filter(OpLog.username.like("%" + str(user).strip() + "%"))
    if action:
        qy = qy.filter(OpLog.action.like("%" + str(action).strip() + "%"))
    total = qy.count()
    rows = qy.order_by(OpLog.id.desc()).offset((p - 1) * n).limit(n).all()
    return {
        "ok": True, "total": total, "page": p, "size": n,
        "rows": [{
            "id": r.id, "username": getattr(r, "username", ""),
            "action": getattr(r, "action", ""), "target": getattr(r, "target", ""),
            "detail": getattr(r, "detail", ""), "ts": str(getattr(r, "ts", "") or ""),
        } for r in rows],
    }


