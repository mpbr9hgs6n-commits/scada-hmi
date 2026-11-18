# -*- coding: utf-8 -*-
"""历史数据（TDengine）：五维度查询 + 按日期/天数删除（提示词 10 第 3 节）。

查询两种入口（同一条 GET）：
  老入口  ?site=S002&point=LEVEL&minutes=30 | from_ts/to_ts&interval=1m
          —— 组态曲线控件在用，保持兼容（limit 5000）
  新入口  ?site=S001&point=LEVEL&year=2026[&month=11][&day=9][&hour=14]
          —— 粒度自动：年/月→按天，日→按分钟，时→按秒（超 2000 条自动降 5 秒）
          —— 不传 point：该站全部点位按点位分组返回；点位 >20 个拒绝

删除（admin）：
  DELETE ?site=S001&point=LEVEL&date=2026-11-09&confirm=1
  DELETE ?site=S001&point=LEVEL&keep_days=30&confirm=1   （keep_days ≥ 7）
  只删数据行不删子表；写 sys_op_log。
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db, td_query, td_exec, td_url_for_site
from ..models import User, OpLog, Point
from ..auth import get_current_user, check_site_permission
from ..core.validate import (require_site, require_point, require_int,
                             require_interval, require_ts, td_str)
from ..service.point_service import hist_table_name

router = APIRouter(prefix="/api", tags=["history"])

# 新入口单次返回上限（提示词 3.1 规则 4）
MAX_POINTS = 2000
# 历史导出单次上限：20 万点位规模下一次拉太多会拖死 TDengine，也导不出可用文件
EXPORT_MAX_ROWS = 500000
# 不指定 point 时，点位数量上限（规则 2）
MAX_SERIES = 20


def _range_by_dims(year, month, day, hour):
    """五个维度 → (起, 止, 粒度, 说明)。年/月按天、日按分钟、时按秒。"""
    if hour is not None:
        start = dt.datetime(year, month or 1, day or 1, hour)
        return start, start + dt.timedelta(hours=1), "1s"
    if day is not None:
        start = dt.datetime(year, month or 1, day)
        return start, start + dt.timedelta(days=1), "1m"
    if month is not None:
        start = dt.datetime(year, month, 1)
        nxt = dt.datetime(year + (month == 12), (month % 12) + 1, 1)
        return start, nxt, "1d"
    start = dt.datetime(year, 1, 1)
    return start, dt.datetime(year + 1, 1, 1), "1d"


def downgrade_gran(gran, n_rows):
    """小时粒度按秒最多 3600 条 > 2000：自动降 5 秒并告知前端（提示词 3.1 规则 4）。

    返回 (新粒度, 提示语)。纯函数，单测直接调（tests/test_10.py）。
    """
    if gran == "1s" and n_rows > MAX_POINTS:
        return "5s", "数据超过 2000 条，已按 5 秒聚合"
    return gran, ""


def _rows_of(data):
    cols = data.get("column_meta", [])
    names = [c[0] for c in cols]
    out = []
    for r in data.get("data", []):
        d = dict(zip(names, r))
        if "ts" in d:
            d["ts"] = str(d.get("ts", ""))[:19]
        if "val" in d:
            d["val"] = None if d["val"] is None else round(float(d["val"]), 4)
        out.append(d)
    return out


@router.get("/history")
async def history(site: str, point: str = None, minutes: str = None,
                  from_ts: str = None, to_ts: str = None, interval: str = None,
                  limit: str = "5000",
                  year: str = None, month: str = None, day: str = None, hour: str = None,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """历史查询（只在 TDengine）。

    安全：site/point 白名单正则、字符串统一 td_str 转义、数值先按字符串收再判范围、
    interval 只允许 1m/5m/1h/1d 形态、开头 check_site_permission。
    """
    site = require_site(site)
    if point:
        point = require_point(point)
    check_site_permission(user, site, db)
    # 一个网关一套独立 TDengine：历史只在站点所属网关的库里，必须按归属路由
    td_url = td_url_for_site(db, site)

    # ---------------- 老入口（组态控件）：保持原有语义 ----------------
    if year is None:
        if not point:
            raise HTTPException(400, "老用法必须指定 point；不指定 point 请用 year 五维查询")
        minutes_n = require_int(minutes, 1, 43200, "minutes")
        limit_n = require_int(limit, 1, 5000, "limit", default=5000)
        interval_s = require_interval(interval)
        f_arg = require_ts(from_ts, "from_ts")
        t_arg = require_ts(to_ts, "to_ts")
        now = dt.datetime.now()
        f = f_arg or (now - dt.timedelta(minutes=minutes_n or 360))
        t = t_arg or now
        if f > t:
            raise HTTPException(400, "from_ts 不能晚于 to_ts")
        where = (f"site={td_str(site)} and point={td_str(point)} "
                 f"and ts >= {td_str(f.strftime('%Y-%m-%d %H:%M:%S'))} "
                 f"and ts <= {td_str(t.strftime('%Y-%m-%d %H:%M:%S'))}")
        if interval_s:
            sql = ("select to_char(_wstart,'yyyy-mm-dd hh24:mi:ss') as ts, "
                   "first(val) as val, avg(q) as q from plant.samples "
                   f"where {where} interval({interval_s})")
        else:
            sql = ("select to_char(ts,'yyyy-mm-dd hh24:mi:ss') as ts, val, q "
                   f"from plant.samples where {where} order by ts asc limit {limit_n}")
        try:
            data = await td_query(sql, td_url)
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        rows = _rows_of(data)
        return {"site": site, "point": point, "count": len(rows), "rows": rows,
                "granularity": interval_s or "raw"}

    # ---------------- 新入口：五维度 + 自动粒度 ----------------
    y = require_int(year, 1970, 2100, "year")
    mo = require_int(month, 1, 12, "month") if month not in (None, "") else None
    d = require_int(day, 1, 31, "day") if day not in (None, "") else None
    h = require_int(hour, 0, 23, "hour") if hour not in (None, "") else None
    try:
        f, t, gran = _range_by_dims(y, mo, d, h)
    except ValueError:
        raise HTTPException(400, "日期不存在（如 2 月 30 日），请检查年/月/日")

    # 不传 point：点位 >20 个拒绝（防止一次拉 20 万条）
    if not point:
        n_pts = db.query(Point).filter(Point.site_id == site).count()
        if n_pts > MAX_SERIES:
            raise HTTPException(400, f"该站点有 {n_pts} 个点位，请指定点位或缩小范围"
                                     f"（不指定时上限 {MAX_SERIES} 个）")

    def _sql(pt=None, g="1m", lim=MAX_POINTS):
        cond = (f"site={td_str(site)} "
                f"and ts >= {td_str(f.strftime('%Y-%m-%d %H:%M:%S'))} "
                f"and ts < {td_str(t.strftime('%Y-%m-%d %H:%M:%S'))}")
        if pt:
            cond += f" and point={td_str(pt)}"
            return ("select to_char(_wstart,'yyyy-mm-dd hh24:mi:ss') as ts, "
                    "avg(val) as val, count(*) as n from plant.samples "
                    f"where {cond} interval({g}) fill(none) limit {lim}")
        return ("select point, to_char(_wstart,'yyyy-mm-dd hh24:mi:ss') as ts, "
                "avg(val) as val, count(*) as n from plant.samples "
                f"where {cond} partition by point interval({g}) fill(none) limit {lim}")

    note = ""
    try:
        if point:
            data = await td_query(_sql(point, gran), td_url)
            rows = _rows_of(data)
            # 小时粒度按秒可能 3600 条 > 2000：自动降 5 秒并告知前端
            new_gran, note = downgrade_gran(gran, len(rows))
            if new_gran != gran:
                data = await td_query(_sql(point, new_gran), td_url)
                rows = _rows_of(data)
                gran = new_gran
            return {"site": site, "point": point, "granularity": gran,
                    "count": len(rows), "rows": rows, "note": note,
                    "range": [f.strftime("%Y-%m-%d %H:%M:%S"),
                              t.strftime("%Y-%m-%d %H:%M:%S")]}
        data = await td_query(_sql(None, gran, MAX_POINTS * MAX_SERIES), td_url)
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    series = {}
    for r in _rows_of(data):
        pt = r.pop("point", "")
        series.setdefault(pt, []).append(r)
    out = []
    for pt, rows in series.items():
        if len(rows) > MAX_POINTS:
            note = "部分点位超过 2000 条，已截断（可指定点位细化）"
            rows = rows[:MAX_POINTS]
        out.append({"point": pt, "count": len(rows), "rows": rows})
    return {"site": site, "granularity": gran, "note": note,
            "range": [f.strftime("%Y-%m-%d %H:%M:%S"), t.strftime("%Y-%m-%d %H:%M:%S")],
            "series": out, "count": sum(x["count"] for x in out)}


@router.delete("/history")
async def delete_history(site: str, point: str, date: str = None,
                         keep_days: str = None, confirm: int = 0,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """按日期 / 只保留最近 N 天删除历史数据（提示词 3.2）。

    - admin only；confirm=1 二次确认；keep_days ≥ 7
    - 只删数据行不删子表（表结构保留，后续还能写）
    - 返回实际删除行数，并写 sys_op_log
    """
    if user.role_code != "admin":
        raise HTTPException(403, "仅管理员可删除历史数据")
    site = require_site(site)
    point = require_point(point)
    check_site_permission(user, site, db)
    td_url = td_url_for_site(db, site)      # 历史在站点所属网关的库里
    if not confirm:
        raise HTTPException(400, "必须二次确认：加 confirm=1")
    if not date and not keep_days:
        raise HTTPException(400, "date 与 keep_days 至少传一个")
    if date and keep_days:
        raise HTTPException(400, "date 与 keep_days 不能同时传")

    if keep_days:
        days = require_int(keep_days, 7, 3650, "keep_days")
        cutoff = dt.datetime.now() - dt.timedelta(days=days)
        f, t = dt.datetime(1970, 1, 1), cutoff
        label = f"保留最近 {days} 天（删除 {cutoff:%Y-%m-%d %H:%M} 之前）"
    else:
        try:
            d0 = dt.datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "date 必须是 YYYY-MM-DD")
        f, t = d0, d0 + dt.timedelta(days=1)
        label = f"{date} 全天"

    try:
        tb = hist_table_name(site, point)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 先数行数（TDengine DELETE 的返回不带行数时用它兜底）
    cnt_sql = (f"select count(*) from plant.{tb} where ts >= "
               f"{td_str(f.strftime('%Y-%m-%d %H:%M:%S'))} and ts < "
               f"{td_str(t.strftime('%Y-%m-%d %H:%M:%S'))}")
    try:
        cdata = await td_query(cnt_sql, td_url)
        will_del = int(cdata["data"][0][0]) if cdata.get("data") else 0
    except RuntimeError as e:
        # 子表不存在（点位从没存过历史）→ 明确告知，不当 500
        if "Table does not exist" in str(e) or "not exist" in str(e):
            return {"ok": True, "deleted_rows": 0, "scope": label,
                    "note": f"点位 {site}.{point} 没有历史子表（从未开过存历史）"}
        raise HTTPException(500, str(e))

    del_sql = (f"delete from plant.{tb} where ts >= "
               f"{td_str(f.strftime('%Y-%m-%d %H:%M:%S'))} and ts < "
               f"{td_str(t.strftime('%Y-%m-%d %H:%M:%S'))}")
    try:
        res = await td_exec(del_sql, td_url)
        if res.get("code") not in (0, None):
            raise RuntimeError(f"TDengine error {res.get('code')}: {res.get('desc')}")
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    deleted = int(res.get("affected_rows") or will_del or 0)
    db.add(OpLog(username=user.username, site_id=site, point_code=point,
                 action="删除历史", old_val=f"{label} 共 {deleted} 行",
                 new_val=f"date={date or ''} keep_days={keep_days or ''}",
                 result="ok"))
    db.commit()
    return {"ok": True, "deleted_rows": deleted, "scope": label,
            "date": date, "keep_days": int(keep_days) if keep_days else None}


# ============================================================================
# 历史数据导出（第 02 章）
#   按「日期区间」导出单个点位的原始数据，CSV 带 BOM（Excel 不乱码）。
#   复用上面老入口的 from_ts/to_ts 语义，不另写一套 TDengine 访问。
# ============================================================================
def _csv_esc(v) -> str:
    """CSV 字段转义：含逗号/双引号/换行就用双引号包起来。"""
    s = "" if v is None else str(v)
    if any(c in s for c in (",", chr(34), chr(10), chr(13))):
        return chr(34) + s.replace(chr(34), chr(34) * 2) + chr(34)
    return s


@router.get("/history/export")
async def history_export(site: str, point: str, from_date: str, to_date: str,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """按日期区间导出单个点位的历史数据。

    from_date / to_date 格式 YYYY-MM-DD：from 取当天 00:00:00，to 取当天 23:59:59。
    超过 EXPORT_MAX_ROWS 直接 400，提示缩小范围（不静默截断）。
    """
    site = require_site(site)
    point = require_point(point)
    check_site_permission(user, site, db)

    try:
        f = dt.datetime.strptime(from_date, "%Y-%m-%d")
        t = dt.datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    except ValueError:
        raise HTTPException(400, "日期格式必须是 YYYY-MM-DD")
    if f > t:
        raise HTTPException(400, "from_ts 不能晚于 to_ts")

    td_url = td_url_for_site(db, site)
    where = (f"site={td_str(site)} and point={td_str(point)} "
             f"and ts >= {td_str(f.strftime('%Y-%m-%d %H:%M:%S'))} "
             f"and ts <= {td_str(t.strftime('%Y-%m-%d %H:%M:%S'))}")

    try:
        cd = await td_query(f"select count(*) as n from plant.samples where {where}", td_url)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    n = 0
    crow = _rows_of(cd)
    if crow:
        try:
            n = int(crow[0].get("n") or 0)
        except (TypeError, ValueError):
            n = 0
    if n > EXPORT_MAX_ROWS:
        raise HTTPException(400, f"该区间共 {n} 条，超过单次导出上限 {EXPORT_MAX_ROWS}，"
                                 f"请缩小日期范围或降低采样密度")

    try:
        data = await td_query(
            f"select to_char(ts,'yyyy-mm-dd hh24:mi:ss') as ts, val, q "
            f"from plant.samples where {where} order by ts asc", td_url)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    rows = _rows_of(data)

    p = db.query(Point).filter(Point.site_id == site, Point.code == point).first()
    pname = (p.name if p else "") or ""
    punit = (p.unit if p else "") or ""
    BOM = chr(0xFEFF)
    NL = chr(10)
    HEADER = ",".join(["时间", "点位编码", "点位名称", "数值", "单位"])

    def gen():
        yield BOM
        yield HEADER + NL
        for r in rows:
            parts = [_csv_esc(r.get("ts")), _csv_esc(point), _csv_esc(pname),
                     _csv_esc(r.get("val")), _csv_esc(punit)]
            yield ",".join(parts) + NL

    fn = f"history_{site}_{point}_{from_date}_{to_date}.csv"
    return StreamingResponse(gen(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{fn}"'})
