# -*- coding: utf-8 -*-
"""点位服务层（提示词 09 第 7 节：insert/update/delete 只实现一次）。

三个录入入口（单个新增 / 批量生成 / 导入）全部走 insert_points；
删除带引用检查；修改改了地址相关字段要清 Redis 旧值并热重载。
"""
import re

from sqlalchemy.orm import Session

from ..models import Point, Page, Alarm, Site
from ..core.validate import validate_point, addr_span


# ---------------- 字段白名单（从请求体里只挑这些，多的忽略） ----------------
POINT_FIELDS = ("code", "name", "descr", "group_name", "sort_no", "addr", "dtype",
                "byte_order", "bit_offset", "poll_ms", "unit", "scale_min",
                "scale_max", "decimals", "rw", "deadband", "save_history",
                "hist_interval", "offset_val", "valuelist_id", "alarm_hh",
                "alarm_h", "alarm_l", "alarm_ll", "alarm_hyst", "alarm_delay",
                "alarm_level", "is_kpi", "write_confirm", "enabled")


def _site_dict(db: Session, site_id: str) -> dict:
    s = db.query(Site).filter(Site.id == site_id).first()
    if not s:
        return {}
    return {"plc_protocol": s.plc_protocol, "protocol": s.plc_protocol,
            "timeout_ms": s.timeout_ms, "default_poll_ms": s.default_poll_ms}


def existing_points(db: Session, site_id: str, exclude_id: int = None):
    q = db.query(Point).filter(Point.site_id == site_id)
    if exclude_id:
        q = q.filter(Point.id != exclude_id)
    return [{"code": p.code, "addr": p.addr, "dtype": p.dtype}
            for p in q.all()]


def validate_rows(db: Session, site_id: str, rows: list, exclude_id: int = None, soft: bool = False):
    """逐行校验（12 条规则一套）。返回 (ok_rows, bad_rows, warnings)。
    bad_rows 里带 row/field/msg，前端预览表直接标红。"""
    site = _site_dict(db, site_id)
    others = existing_points(db, site_id, exclude_id)
    ok_rows, bad_rows, warns = [], [], []
    seen = []
    for i, r in enumerate(rows, start=1):
        p = {k: r.get(k) for k in POINT_FIELDS if k in r}
        # _conflict 不是点位字段，会被上面的过滤扔掉，必须显式带上；
        # 否则前端按行下发的"覆盖/忽略"会全部退化成默认 allow。
        if r.get("_conflict"):
            p["_conflict"] = r["_conflict"]
        # 不能按 code 把 others 里的同编码项排掉：批量导入是「新增」场景，
        # 排掉自己会让「编码已存在」检查对全大写编码完全失效（实测 13 个重复点位全通过）。
        # 「编辑单个点位」的排除由 existing_points(db, site_id, exclude_id) 负责。
        inner = list(others) + [{"code": c, "addr": a, "dtype": d} for c, a, d in seen]
        errors, warnings = validate_point(p, site, inner, row=i)
        for w in warnings:
            if w not in warns:
                warns.append(w)
        if errors:
            bad_rows.append({"row": i, "code": p.get("code"),
                             "errors": errors})
            if soft:
                # 软校验（用户 2026-11：即使有错也要导入）
                # 不再 continue，把错误挂在这行上一起交给落库，最后写进 import_error 列
                p["_errors"] = errors
                ok_rows.append(p)
                seen.append((str(p.get("code") or ""), p.get("addr") or "",
                             p.get("dtype") or "float32"))
            continue
        ok_rows.append(p)
        seen.append((str(p["code"]).upper(), p.get("addr") or "", p.get("dtype") or "float32"))
    return ok_rows, bad_rows, warns


def hist_table_name(site_id: str, code: str) -> str:
    """子表名 d_{site}_{code}，全部小写只留 [a-z0-9_]（提示词 3.4）"""
    tb = f"d_{site_id.lower()}_{code.lower()}"
    tb = re.sub(r"[^a-z0-9_]", "", tb)
    if not re.fullmatch(r"[a-z0-9_]{1,192}", tb):
        raise ValueError(f"非法表名 {tb}")
    return tb


async def ensure_history_tables(site_id: str, rows: list):
    """store=1 的点位建历史子表，失败不阻断保存（铁律 3.4-2：
    写入时 INSERT ... USING 会自动补建，双保险）。
    批量 50 条一批；REST 不支持多语句时自动退回逐条。"""
    from ..db import td_exec
    todo = [r for r in rows if int(r.get("save_history") or 0) == 1]
    if not todo:
        return 0
    stmts = []
    for r in todo:
        try:
            tb = hist_table_name(site_id, r["code"])
        except ValueError:
            continue
        # 注意：samples 超级表只有 2 个 TAG（site/point）——多给会报
        # "number of tags mismatch" 且被静默吞掉，子表一直建不出来（实测踩过）
        stmts.append(f"CREATE TABLE IF NOT EXISTS plant.{tb} USING plant.samples TAGS "
                     f"('{site_id}', '{r['code']}')")
    made = 0
    for i in range(0, len(stmts), 50):
        batch = stmts[i:i + 50]
        try:
            r = await td_exec("; ".join(batch))
            if r.get("code") == 0:
                made += len(batch)
                continue
        except Exception:
            pass
        # 多语句不被接受 → 逐条（仍然算同一批，只是网络往返多几次）
        for s in batch:
            try:
                r = await td_exec(s)
                if r.get("code") == 0:
                    made += 1
            except Exception:
                import logging
                logging.getLogger("app.point_service").warning(
                    "站点 %s 历史子表建表失败（写入时会自动补建）：%s", site_id, s[:120])
    return made


async def insert_points(db: Session, site_id: str, rows: list, on_conflict: str = "allow"):
    """唯一写入路径。rows 必须已经过 validate_rows（soft 模式下行里带 _errors）。

    冲突处理（用户 2026-11：一切都以人的思想为准则，不再"有错就不让导"）：
      allow      默认。code 已存在 → 跳过该行（唯一约束挡着，插不进）；
                 地址重叠 → 照样插入，两个点位共存（库里 addr 没有唯一约束）
      overwrite  覆盖。code 已存在 → 更新该点位的配置；
                 地址重叠 → 删掉占着该地址的旧点位再插
      ignore     忽略。code 已存在或地址重叠 → 都跳过该行

    每行的校验问题写进 import_error 列，不阻断导入。
    """
    mode = (on_conflict or "allow").lower()
    if mode not in ("allow", "overwrite", "ignore"):
        mode = "allow"

    created = updated = skipped = 0
    touched = []
    for p in rows:
        row = dict(p)
        errs = row.pop("_errors", None) or []
        # 行级冲突策略优先（前端勾选后按行下发：选中的覆盖、未选中的忽略）
        row_mode = str(row.pop("_conflict", None) or mode).lower()
        if row_mode not in ("allow", "overwrite", "ignore"):
            row_mode = mode
        row["import_error"] = ("; ".join(str(e.get("msg") or "") for e in errs))[:250] or None
        code = row.get("code")
        if not code:
            skipped += 1
            continue

        exist = db.query(Point).filter(Point.site_id == site_id, Point.code == code).first()
        if exist:
            if row_mode == "overwrite":
                for k, v in row.items():
                    if k in POINT_FIELDS:
                        setattr(exist, k, v)
                exist.import_error = row.get("import_error")
                updated += 1
                touched.append({"code": code, "action": "updated"})
            else:
                skipped += 1
                touched.append({"code": code, "action": "skipped", "why": "编码已存在"})
            continue

        # 地址重叠：库里 addr 无唯一约束，allow 直接共存
        if row_mode in ("overwrite", "ignore"):
            try:
                _area, s0, e0 = addr_span(
                    _site_proto(db, site_id), row.get("addr") or "", row.get("dtype") or "float32")
                clash = []
                for o in db.query(Point).filter(Point.site_id == site_id).all():
                    if (o.addr or "") == "" or o.code == code:
                        continue
                    try:
                        a2, s2_, e2 = addr_span(_site_proto(db, site_id), o.addr, o.dtype or "float32")
                    except Exception:
                        continue
                    if a2 == _area and s0 < e2 and s2_ < e0:
                        clash.append(o)
                if clash:
                    if row_mode == "ignore":
                        skipped += 1
                        touched.append({"code": code, "action": "skipped",
                                        "why": "地址重叠 " + ",".join(x.code for x in clash[:3])})
                        continue
                    for o in clash:      # overwrite：删掉占地址的旧点位
                        db.delete(o)
                    touched.append({"code": code, "action": "overwrote",
                                    "removed": [x.code for x in clash]})
            except Exception:
                pass

        db.add(Point(site_id=site_id, **{k: v for k, v in row.items() if k in POINT_FIELDS or k == "import_error"}))
        created += 1
        touched.append({"code": code, "action": "created"})

    db.commit()
    await ensure_history_tables(site_id, [])
    from ..core.gateway import notify_reload
    await notify_reload(site_id)
    return {"created": created, "updated": updated, "skipped": skipped, "touched": touched}


def _site_proto(db: Session, site_id: str) -> str:
    s = db.query(Site).filter(Site.id == site_id).first()
    return ((s.plc_protocol or s.protocol or "") if s else "") or ""


# ---------------- 删除：引用检查（提示词 09 第 3.2 节） ----------------
def point_references(db: Session, site_id: str, code: str):
    """检查组态画面与报警对点位的引用。返回 (画面名列表, 活动报警条数)
    画面里定站写法是 "S001.LEVEL"——JSON 序列化后 LEVEL 前面是引号不是点，
    所以 LIKE 不能带前导点（否则定站绑定永远拦不住，实测踩过）。
    @CurrentSite + '.LEVEL' 模板写法保留原模式。宁可误拦（保守）不可漏拦。"""
    like_site = f"%{site_id}.{code}%"
    like_cur = f"%.{code}'%"
    pages = db.query(Page).filter(
        Page.json.like(like_site) | Page.json.like(like_cur)).all()
    page_names = [p.name for p in pages]
    alarms = db.query(Alarm).filter(Alarm.site_id == site_id,
                                    Alarm.point_code == code,
                                    Alarm.state.in_([0, 1])).count()
    return page_names, alarms


async def delete_point(db: Session, p: Point):
    """删点位：硬删 MySQL 行 + 删 Redis field；TDengine 子表与历史一律保留。"""
    from ..db import redis_client
    site_id, code = p.site_id, p.code
    db.delete(p)
    db.commit()
    try:
        await redis_client.hdel(f"rt:{site_id}", code)
    except Exception:
        pass
    from ..core.gateway import notify_reload
    await notify_reload(site_id)


async def clear_rt_value(site_id: str, code: str):
    """改地址/类型后旧值作废（提示词 09 第 3.3 节）。"""
    from ..db import redis_client
    try:
        await redis_client.hdel(f"rt:{site_id}", code)
    except Exception:
        pass


async def save_point_update(db: Session, p: Point, fields: dict):
    """修改点位的唯一落库口（API 层只挑字段，不做 db.commit）。"""
    for k in POINT_FIELDS:
        if k in fields:
            setattr(p, k, fields[k])
    db.commit()


async def set_point_enabled(db: Session, p: Point) -> int:
    """启用/停用（停用 ≠ 删除：保留配置、停采集）。返回新状态。
    注意函数名不能叫 toggle_point——会被 api/points.py 的同名路由函数遮蔽，
    函数体里 await 到的就是路由自己（实测 500 踩过）。"""
    p.enabled = 0 if p.enabled else 1
    db.commit()
    return p.enabled
