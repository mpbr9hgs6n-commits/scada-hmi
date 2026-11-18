# -*- coding: utf-8 -*-
"""点位管理（提示词 09 第 3/5/6 节）。

三个录入入口共用一套校验（core/validate.py::validate_point）和一条
写入路径（service/point_service.py::insert_points）：
  - POST /api/point          单个新增（校验不过 400，带字段+中文原因）
  - POST /api/point/batch    批量生成 → 只返回预览，不落库
  - POST /api/point/import   上传 CSV/XLSX → 只返回预览，不落库
  - POST /api/point/commit   预览确认后真正落库（三个入口共用）
删除带引用检查（组态画面 / 活动报警）；停用与删除是两个按钮、两个语义。
"""
import csv
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db, redis_client
from ..models import Point, Site, User
from ..auth import get_current_user, check_site_permission, site_scope_ids
from ..service import point_service as svc
from ..service.point_service import (POINT_FIELDS, validate_rows, insert_points,
                                     point_references, delete_point,
                                     clear_rt_value, ensure_history_tables,
                                     save_point_update, set_point_enabled)
from ..core.gateway import notify_reload

router = APIRouter(prefix="/api", tags=["points"])

# 同步 Redis 客户端：只在「带当前值」的查询里用（路由是同步函数）
_sync_redis = None


def _rt_values(site_id: str):
    try:
        global _sync_redis
        import redis as _redis
        from .. import config
        if _sync_redis is None:
            _sync_redis = _redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT,
                                       decode_responses=True, socket_timeout=2)
        raw = _sync_redis.hgetall(f"rt:{site_id}") or {}
    except Exception:
        return {}
    out = {}
    for code, s in raw.items():
        try:
            v, ts, q = str(s).split("|")
            out[code] = {"val": float(v), "ts": int(ts), "q": int(q)}
        except Exception:
            continue
    return out


def _require_admin(user: User):
    if user.role_code != "admin":
        raise HTTPException(403, "仅管理员可管理点位")


def _item(p: Point, val=None):
    it = {"id": p.id, "site_id": p.site_id, "code": p.code, "name": p.name,
          "descr": p.descr, "group_name": p.group_name, "addr": p.addr,
          "dtype": p.dtype, "byte_order": p.byte_order, "bit_offset": p.bit_offset,
          "poll_ms": p.poll_ms, "unit": p.unit, "scale_min": p.scale_min,
          "scale_max": p.scale_max, "decimals": p.decimals, "rw": p.rw,
          "deadband": p.deadband, "save_history": p.save_history,
          "enabled": p.enabled,
          # 导入时的校验问题（用户 2026-11：不阻断导入，问题记在这里给人看）
          "import_error": getattr(p, "import_error", None)}
    if val is not None:
        it["value"] = val
    return it


# ---------------- 1. 列表 ----------------
@router.get("/points")
async def list_points(site_id: str = None, site: str = None, kw: str = "", q: str = "",
                enabled: int = None, rw: int = None,
                page: int = 1, size: int = None, limit: int = None,
                with_value: int = 0,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """点位列表 / 搜索（组态变量选择器与点位管理页共用）。
    兼容两套参数名：site_id/site、kw/q（q 是老变量选择器的名字）。"""
    sid = site_id or site
    n = limit if limit is not None else (size if size is not None else 50)
    # 上限 2000：组态变量选择器要能列出该站全部启用点位（S005 这类模拟站有 1000 个），
    # 卡在 200 会让「选不到 200 号以后的点位」变成静默故障（4.3 规则 1/2）
    n = max(1, min(int(n), 2000))
    page = max(1, int(page))

    qy = db.query(Point)
    if sid:
        check_site_permission(user, sid, db)
        qy = qy.filter(Point.site_id == sid)
    else:
        scope = site_scope_ids(user, db)
        if scope is not None:
            if not scope:
                return {"total": 0, "items": [], "has_more": False}
            qy = qy.filter(Point.site_id.in_(scope))
    key = (kw or q or "").strip()
    if key:
        like = f"%{key}%"
        qy = qy.filter(Point.code.like(like) | Point.name.like(like))
    if rw is not None:
        qy = qy.filter(Point.rw == int(rw))
    if enabled is not None:
        qy = qy.filter(Point.enabled == int(enabled))

    total = qy.count()
    rows = qy.order_by(Point.site_id, Point.code).offset((page - 1) * n).limit(n).all()

    vals = {}
    if with_value:
        if sid:
            vals = {sid: _rt_values(sid)}
        else:
            for s2 in list({p.site_id for p in rows})[:5]:
                vals[s2] = _rt_values(s2)
    # 站点在线状态：网关心跳写在 Redis site:status:{id}（1=在线 2=离线）。
    # 点位"在采"不能只看 enabled —— 站点离线或没配心跳时，enabled=1 也一次都不采。
    online_map = {}
    try:
        sids = sorted({p.site_id for p in rows if p.site_id})
        if sids:
            vs = await redis_client.mget([f"site:status:{x}" for x in sids])
            for sid2, v in zip(sids, vs):
                if v is not None:
                    online_map[sid2] = (str(v) == "1")
    except Exception:
        online_map = {}

    items = []
    for p in rows:
        v = (vals.get(p.site_id) or {}).get(p.code)
        dec = p.decimals if p.decimals is not None else 2
        it = _item(p, round(v["val"], dec) if v else None)
        it["site_online"] = online_map.get(p.site_id)   # None = 该站没配心跳
        items.append(it)
    return {"total": total, "items": items, "has_more": page * n < total}


# ---------------- 2. 单个新增 ----------------
def _reload_err(rr) -> str:
    """网关热重载失败时给前端的提示（空串 = 成功）。

    不能吞掉：配置已落库但网关没重载，用户以为改好了，实际采集还是老配置，
    下次写这个点位就报「点位不存在」。
    """
    if (rr or {}).get("ok"):
        return ""
    return str((rr or {}).get("error") or "网关未响应（容器可能没在运行）")[:160]


def _check_point_quota(db: Session, sid: str, adding: int):
    """社区版额度：每台 PLC（每个站点）最多 MAX_POINTS_PER_SITE 个采集点。

    只拦新增/导入，不拦"编辑已有点位"（编辑时 adding 传 0）。
    """
    from ..core import edition as _ed
    if _ed.MAX_POINTS_PER_SITE is None:
        return
    cur = db.query(Point).filter(Point.site_id == sid).count()
    add = int(adding or 0)
    if cur + add > _ed.MAX_POINTS_PER_SITE:
        raise HTTPException(403, _ed.points_message(cur, add))


@router.post("/point")
async def create_point(body: dict, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    _require_admin(user)
    sid = body.get("site_id")
    if not sid or not db.query(Site).filter(Site.id == sid).first():
        raise HTTPException(400, "站点不存在")
    check_site_permission(user, sid, db)
    _check_point_quota(db, sid, 1)
    row = {k: body.get(k) for k in POINT_FIELDS if k in body}
    ok_rows, bad_rows, warns = validate_rows(db, sid, [row])
    if bad_rows:
        e = bad_rows[0]["errors"][0]
        raise HTTPException(400, f"第 {bad_rows[0]['row']} 行 {e['field']}：{e['msg']}")
    n = await insert_points(db, sid, ok_rows)
    # 新增点位必须通知网关重载：不通知的话网关内存里没有这个点位，
    # 组态上写它会报「点位不存在」，而界面上明明刚保存成功。
    rr = await notify_reload(sid)
    return {"ok": True, "created": n, "warnings": warns,
            "reload_ok": bool((rr or {}).get("ok")),
            "reload_err": _reload_err(rr)}


# ---------------- 3. 批量生成（只预览） ----------------
def _gen_addr(protocol: str, start: str, i: int, step: int, dtype: str) -> str:
    """按起始地址推第 i 个地址：VD2000+4i / D200+2i / 40001+2i / HR8+2i
    （前缀原样保留，只对末尾数字做加法）"""
    a = start.strip().upper()
    m = re.match(r"^(.*?)(\d+)$", a)
    if not m:
        raise ValueError(f"起始地址 {start} 末尾必须是数字")
    return f"{m.group(1)}{int(m.group(2)) + i * step}"


@router.post("/point/batch")
def batch_points(body: dict, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """批量生成：起始地址 + 数量 + 步长 + 类型 + 名称模板 → 预览（不落库）"""
    _require_admin(user)
    sid = body.get("site_id")
    s = db.query(Site).filter(Site.id == sid).first() if sid else None
    if not s:
        raise HTTPException(400, "站点不存在")
    check_site_permission(user, sid, db)
    try:
        start = str(body["start_addr"]).strip()
        count = int(body.get("count") or 0)
        step = int(body.get("step") or 2)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "start_addr / count / step 必填且为数字")
    if not 1 <= count <= 2000:
        raise HTTPException(400, "数量必须在 1~2000")
    _check_point_quota(db, sid, count)
    dtype = body.get("dtype") or "float32"
    tpl = body.get("name_tpl") or "点位{n}"
    prefix = (body.get("prefix") or "P").upper()
    rows = []
    for i in range(count):
        try:
            addr = _gen_addr(s.plc_protocol, start, i, step, dtype)
        except ValueError as e:
            raise HTTPException(400, str(e))
        num = re.match(r"^(.*?)(\d+)$", addr).group(2)
        rows.append({"code": f"{prefix}{num}", "name": tpl.format(n=i + 1, a=addr),
                     "addr": addr, "dtype": dtype,
                     "unit": body.get("unit"), "rw": body.get("rw", 0),
                     "save_history": body.get("save_history", 0),
                     "decimals": body.get("decimals", 2),
                     "poll_ms": body.get("poll_ms")})
    ok_rows, bad_rows, warns = validate_rows(db, sid, rows)
    return {"ok": True, "preview": ok_rows, "bad_rows": bad_rows,
            "warnings": warns, "site_id": sid}


# ---------------- 4. 导入（只预览） ----------------
IMPORT_COLS = ["code", "name", "addr", "dtype", "unit", "scale_min", "scale_max",
               "decimals", "rw", "deadband", "save_history", "poll_ms", "rw_note"]

# 导出模板用中文表头（用户 2026-11 要求），导回来必须能认。
# 这张表把「导出的中文列名」映射回内部英文 key；英文表头继续按原样通过。
# 注意：站点名称列只用于人看，导入的站点来自 URL 参数 site_id，这里映射到 site_name
# 只是为了让该列不报错，不会真的按它分派。
HEAD_CN_MAP = {
    "站点名称": "site_name",
    "点位名称": "name",
    "寄存器地址": "addr",
    "数据类型": "dtype",
    "读/写标记": "rw",
    "是否存档": "save_history",
}


def _parse_upload(data: bytes, filename: str):
    """CSV（UTF-8/GBK）/ XLSX → [{列: 值}]。第一行必须是表头（中文或英文列名）。"""
    name = (filename or "").lower()
    if name.endswith(".csv") or name.endswith(".txt"):
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(400, "CSV 编码认不出（支持 UTF-8 / GBK）")
        # 导出文件首行是 # 开头的注释（台账说明）。直接交给 DictReader 会被
        # 当成表头，导致整个文件解析失败 —— 先丢掉 # 开头的行再解析。
        kept = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        return list(csv.DictReader(io.StringIO(chr(10).join(kept))))
    if name.endswith(".xlsx"):
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            # 轻量 xlsx 读取：不引 openpyxl，直接解 zip 读 sheet1（单元格都是字符串
            # 或数字的常规导出都能读；复杂合并单元格不在导入场景里）
            zf = zipfile.ZipFile(io.BytesIO(data))
            shared = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                for si in root.findall(f"{ns}si"):
                    shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
            root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
            ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            rows = []
            for row in root.iter(f"{ns}row"):
                cells = {}
                for c in row.iter(f"{ns}c"):
                    ref = c.get("r") or ""
                    col = re.match(r"([A-Z]+)", ref).group(1) if ref else ""
                    t = c.get("t")
                    v = c.find(f"{ns}v")
                    if v is None:
                        isel = c.find(f"{ns}is")
                        cells[col] = "".join(x.text or "" for x in isel.iter(f"{ns}t")) if isel is not None else ""
                    elif t == "s":
                        cells[col] = shared[int(v.text)]
                    else:
                        cells[col] = v.text or ""
                rows.append(cells)
            if not rows:
                return []
            header = rows[0]
            cols = sorted(header.keys(), key=lambda x: (len(x), x))
            out = []
            for r in rows[1:]:
                out.append({header[c]: r.get(c, "") for c in cols if header[c]})
            return out
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"XLSX 解析失败：{e}")
    raise HTTPException(400, "只支持 .csv / .xlsx 文件")


@router.post("/point/import")
async def import_points(site_id: str, file: UploadFile = File(...),
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """上传 → 解析 → 逐行校验 → 预览（标红错误行）。不落库。"""
    _require_admin(user)
    s = db.query(Site).filter(Site.id == site_id).first()
    if not s:
        raise HTTPException(400, "站点不存在")
    check_site_permission(user, site_id, db)
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "文件超过 5MB")
    raw = _parse_upload(data, file.filename)
    if not raw:
        raise HTTPException(400, "文件里没有数据行")
    rows = []
    for i, r in enumerate(raw, start=1):
        low = {str(k).strip().lower(): (v if v is not None else "") for k, v in r.items()}
        # 中文表头归一化：导出模板是中文的，导回来要能被下面的英文逻辑识别。
        # 英文表头 HEAD_CN_MAP.get 不到就原样保留，两种都能用。
        if any(k in HEAD_CN_MAP for k in low):
            low = {HEAD_CN_MAP.get(k, k): v for k, v in low.items()}
        p = {}
        for k in POINT_FIELDS:
            v = low.get(k, "")
            if k in ("code", "name", "addr", "dtype", "unit", "byte_order"):
                p[k] = str(v).strip() if v != "" else None
            elif v not in ("", None):
                try:
                    p[k] = int(float(v))
                except ValueError:
                    p[k] = v
        if p.get("code") is None and p.get("addr") is None:
            continue          # 空行
        if not p.get("dtype"):
            p["dtype"] = "float32"
        rows.append(p)
    # 软校验（用户 2026-11：即使有错也要能导入）：
    # 有问题的行不再被剔出 preview，而是带着 errors 一起返回，前端逐行标出来。
    ok_rows, bad_rows, warns = validate_rows(db, site_id, rows, soft=True)
    return {"ok": True, "preview": ok_rows, "bad_rows": bad_rows,
            "warnings": warns, "site_id": site_id, "total": len(rows),
            "with_errors": sum(1 for r in ok_rows if r.get("_errors"))}


# ---------------- 5. 预览确认后落库（三入口唯一写入路径） ----------------
@router.post("/point/commit")
async def commit_points(body: dict, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    _require_admin(user)
    sid = body.get("site_id")
    if not sid or not db.query(Site).filter(Site.id == sid).first():
        raise HTTPException(400, "站点不存在")
    check_site_permission(user, sid, db)
    rows = body.get("rows") or []
    if not rows:
        raise HTTPException(400, "没有可导入的行")
    if len(rows) > 2000:
        raise HTTPException(400, "单次最多 2000 行，请分批")
    # 社区版额度：overwrite 不新增点数，只有 allow/ignore 会新增，保守按总行数算
    _on_cf = str(body.get("on_conflict") or "allow").lower()
    if _on_cf != "overwrite":
        _check_point_quota(db, sid, len(rows))
    # 服务端重新校验（预览结果不可信），但用软模式：有错也照样落库，
    # 问题写进 import_error 列，在点位列表里显示（用户 2026-11 要求）。
    on_conflict = str(body.get("on_conflict") or "allow").lower()
    ok_rows, bad_rows, warns = validate_rows(db, sid, rows, soft=True)
    res = await insert_points(db, sid, ok_rows, on_conflict=on_conflict)
    rr = await notify_reload(sid)
    return {"ok": True, "created": res["created"], "updated": res["updated"],
            "skipped": res["skipped"], "touched": res["touched"],
            "bad_rows": bad_rows, "warnings": warns, "on_conflict": on_conflict,
            "reload_ok": bool((rr or {}).get("ok")),
            "reload_err": _reload_err(rr)}


# ---------------- 6. 修改 ----------------
@router.put("/point/{pid}")
async def update_point(pid: int, body: dict, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    _require_admin(user)
    p = db.query(Point).filter(Point.id == pid).first()
    if not p:
        raise HTTPException(404, "点位不存在")
    check_site_permission(user, p.site_id, db)
    # code / site_id 不允许改（提示词 09 第 3.3 节）
    for k in ("code", "site_id"):
        if k in body and str(body[k]) != str(getattr(p, k)):
            raise HTTPException(400, f"{k} 不允许修改（改名等于断链，删除后重建）")
    row = {k: body.get(k) for k in POINT_FIELDS if k in body}
    row["code"] = p.code
    ok_rows, bad_rows, _ = validate_rows(db, p.site_id, [row], exclude_id=p.id)
    if bad_rows:
        e = bad_rows[0]["errors"][0]
        raise HTTPException(400, f"{e['field']}：{e['msg']}")
    addr_changed = any(k in body and str(body.get(k)) != str(getattr(p, k) or "")
                       for k in ("addr", "dtype", "byte_order", "bit_offset"))
    was_storing = bool(p.save_history)
    await save_point_update(db, p, body)
    # 这次才打开存历史的点位补建子表
    if int(body.get("save_history") or 0) == 1 and not was_storing:
        await ensure_history_tables(p.site_id, [{"code": p.code, "dtype": p.dtype,
                                                 "unit": p.unit}])
    if addr_changed:
        await clear_rt_value(p.site_id, p.code)   # 旧值作废，不是 0
    rr = await notify_reload(p.site_id)
    return {"ok": True, "addr_changed": addr_changed,
            "reload_ok": bool((rr or {}).get("ok")),
            "reload_err": "" if (rr or {}).get("ok") else str((rr or {}).get("error") or "网关未响应")[:160]}


# ---------------- 7/8. 删除（单个 / 批量，带引用检查） ----------------
# 注意：/point/batch 必须定义在 /point/{pid} 之前，否则 FastAPI 按定义顺序
# 会把 "batch" 当 pid 解析（int 解析失败 422），批量删除永远走不到。
@router.delete("/point/batch")
async def remove_points(body: dict, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """批量删除：逐个检查，返回成功/失败清单，不允许「部分成功但不告知」"""
    _require_admin(user)
    ids = body.get("ids") or []
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    deleted, failed, touched_sites = [], [], []
    for pid in ids:
        p = db.query(Point).filter(Point.id == int(pid)).first()
        if not p:
            failed.append({"id": pid, "code": "?", "reason": "点位不存在"})
            continue
        try:
            check_site_permission(user, p.site_id, db)
        except HTTPException:
            failed.append({"id": pid, "code": p.code, "reason": "无该站点权限"})
            continue
        pages, alarms = point_references(db, p.site_id, p.code)
        if pages:
            failed.append({"id": pid, "code": p.code,
                           "reason": f"被 {len(pages)} 张画面引用（{'、'.join(pages[:5])}）"})
            continue
        if alarms:
            failed.append({"id": pid, "code": p.code,
                           "reason": f"有 {alarms} 条活动报警"})
            continue
        await delete_point(db, p)
        deleted.append(p.code)
        if p.site_id not in touched_sites:
            touched_sites.append(p.site_id)
    # 涉及的每个站点各通知一次（一次删除可能跨站点）
    reloads = {}
    for _sid in touched_sites:
        _rr = await notify_reload(_sid)
        reloads[_sid] = bool((_rr or {}).get("ok"))
    return {"ok": True, "deleted": deleted, "failed": failed, "reload_ok": reloads}


@router.delete("/point/{pid}")
async def remove_point(pid: int, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    _require_admin(user)
    p = db.query(Point).filter(Point.id == pid).first()
    if not p:
        raise HTTPException(404, "点位不存在")
    check_site_permission(user, p.site_id, db)
    pages, alarms = point_references(db, p.site_id, p.code)
    if pages:
        raise HTTPException(409, f"点位 {p.code} 被 {len(pages)} 张画面引用："
                                 f"{'、'.join(pages[:10])}；先在画面里解除绑定再删除")
    if alarms:
        raise HTTPException(409, f"点位 {p.code} 有 {alarms} 条未确认/未恢复的报警，"
                                 f"先到报警中心处理")
    sid_del = p.site_id
    await delete_point(db, p)
    rr = await notify_reload(sid_del)      # 删了也要通知，否则网关还在读这个地址
    return {"ok": True, "history_kept": True,
            "reload_ok": bool((rr or {}).get("ok")),
            "reload_err": _reload_err(rr)}


# ---------------- 9. 启用/停用 ----------------
@router.post("/point/{pid}/toggle")
async def toggle_point(pid: int, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """停用 ≠ 删除：保留配置、停止采集（提示词 09 第 3.3 节）"""
    _require_admin(user)
    p = db.query(Point).filter(Point.id == pid).first()
    if not p:
        raise HTTPException(404, "点位不存在")
    check_site_permission(user, p.site_id, db)
    enabled = await set_point_enabled(db, p)
    rr = await notify_reload(p.site_id)
    return {"ok": True, "enabled": enabled,
            "reload_ok": bool((rr or {}).get("ok")),
            "reload_err": "" if (rr or {}).get("ok") else str((rr or {}).get("error") or "网关未响应")[:160]}
