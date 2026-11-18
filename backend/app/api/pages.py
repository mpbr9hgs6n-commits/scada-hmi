import base64
import binascii
import json
import os
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import Page, Point, PointMap, Site, User
from ..auth import get_current_user

router = APIRouter(prefix="/api", tags=["pages"])

# 允许编辑/删除画面的角色（与保存一致；设为模板、绑定站点另限管理员）
EDIT_ROLES = ("admin", "operator")

# 提示词 10 §4.4：开发阶段组态只有一张固定画面，主键固定为 1
FIXED_PAGE_ID = 1

# 缩略图（P8）：存文件不塞 json —— 400×225 PNG 约 30KB，base64 塞进 page.json 会把表撑爆
THUMB_DIR = os.getenv("THUMB_DIR", "/data/thumbs")
THUMB_MAX = 2 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _thumb_path(pid: int) -> str:
    return os.path.join(THUMB_DIR, "%d.png" % pid)


def _has_thumb(pid: int) -> bool:
    try:
        return os.path.getsize(_thumb_path(pid)) > 0
    except OSError:
        return False


def _count_items(raw: str) -> int:
    """画面对象数：解析 json 取 items 长度，脏数据按 0 处理，绝不因一条坏数据整表报错"""
    try:
        d = json.loads(raw or "{}")
        items = d.get("items")
        return len(items) if isinstance(items, list) else 0
    except Exception:
        return 0


@router.get("/pages")
def list_pages(kind: str = None, site_id: str = None, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    q = db.query(Page)
    if kind:
        q = q.filter(Page.kind == kind)
    if site_id:
        q = q.filter(Page.site_id == site_id)
    rows = q.order_by(Page.id).all()
    return {"items": [{"id": p.id, "name": p.name, "kind": p.kind,
                       "template_id": p.template_id, "site_id": p.site_id,
                       "locked": p.locked, "objects": _count_items(p.json),
                       # 14 号：发布状态（画面列表页和 /publish 目录树都要用）
                       "published": p.published or 0,
                       "pub_sort": p.pub_sort or 0,
                       # 缩略图只给「有没有」，路径由前端拼 /api/page/{id}/thumb.png?v=更新时间
                       "thumb": _has_thumb(p.id),
                       "updated_at": str(p.updated_at or "")}
                      for p in rows]}


# ===================== 14 号：发布 =====================
@router.post("/page/{pid}/publish")
def publish_page(pid: int, body: dict, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """发布 / 取消发布一张组态画面。

    只有 kind='scada' 能发布——video_wall 有自己的播放页（/video/wall/:id/play），
    不参与 /publish 的目录树。
    """
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    p = db.query(Page).filter(Page.id == pid).first()
    if not p:
        raise HTTPException(404, "画面不存在")
    if p.kind != "scada":
        raise HTTPException(400, "只有组态画面能发布；视频墙请用它的播放页")

    want = 1 if body.get("published") else 0
    p.published = want
    if want and not p.pub_sort:
        # 首次发布：排到末尾（步长 10，方便以后插队）
        mx = db.query(func.max(Page.pub_sort)).scalar() or 0
        p.pub_sort = int(mx) + 10
    db.commit()
    return {"ok": True, "id": p.id, "published": p.published, "pub_sort": p.pub_sort}


@router.put("/pages/publish-order")
def set_publish_order(body: dict, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """批量调整发布排序：body {"order": [3, 1, 2]} 按数组顺序重排"""
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    order = body.get("order") or []
    if not isinstance(order, list):
        raise HTTPException(400, "order 必须是数组")
    for i, pid in enumerate(order):
        p = db.query(Page).filter(Page.id == int(pid)).first()
        if p:
            p.pub_sort = (i + 1) * 10
    db.commit()
    return {"ok": True, "count": len(order)}


@router.get("/page/{pid}")
def get_page(pid: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    p = db.query(Page).filter(Page.id == pid).first()
    if not p:
        raise HTTPException(404, "画面不存在")
    try:
        data = json.loads(p.json) if p.json else {}
    except Exception:
        data = {}
    return {"id": p.id, "name": p.name, "kind": p.kind, "site_id": p.site_id,
            "template_id": p.template_id, "locked": p.locked, "json": data,
            "updated_at": str(p.updated_at or "")}


@router.post("/page")
def save_page(body: dict, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    if body.get("id"):
        p = db.query(Page).filter(Page.id == body["id"]).first()
        if not p:
            raise HTTPException(404, "画面不存在")
        if p.locked:
            raise HTTPException(403, "画面已锁定，请先在画面树里解锁")
        p.name = body.get("name", p.name)
        p.json = json.dumps(body.get("json"), ensure_ascii=False)
    else:
        kind = body.get("kind", "scada")
        p = Page(name=body.get("name", "未命名画面"), kind=kind,
                 site_id=body.get("site_id"),
                 # 子画面挂在父画面下（template_id 指向父画面），模板本身不能当子画面
                 template_id=body.get("template_id") if kind != "template" else None,
                 json=json.dumps(body.get("json", {}), ensure_ascii=False))
        db.add(p)
    db.commit()
    return {"ok": True, "id": p.id}


@router.put("/page/{pid}")
def update_page_meta(pid: int, body: dict, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """画面属性 + 画面内容。

    提示词 10 §4.4：保存固定走 `PUT /api/page/1`，body 里带 `json` 就存画面内容，
    只带 name/locked 就只改元数据。开发阶段界面不提供新建/删除画面入口；
    `POST /api/page`（新建）保留给后期多画面与自动巡检用例，前端不再调用。
    """
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    p = db.query(Page).filter(Page.id == pid).first()
    if not p:
        raise HTTPException(404, "画面不存在")

    # 画面内容：整份 json 覆盖（前端是唯一的写入方，不做字段级合并）
    if "json" in body:
        data = body.get("json")
        if not isinstance(data, dict):
            raise HTTPException(400, "json 必须是对象")
        if p.locked:
            raise HTTPException(403, "画面已锁定，请先解锁再改")
        p.json = json.dumps(data, ensure_ascii=False)

    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "画面名称不能为空")
        if len(name) > 64:
            raise HTTPException(400, "画面名称最长 64 个字符")
        p.name = name

    # 设为模板：kind=template 且 site_id 必须为空（模板不属于任何站点）
    if body.get("kind") == "template":
        if user.role_code != "admin":
            raise HTTPException(403, "仅管理员可设为模板")
        p.kind = "template"
        p.site_id = None

    # 绑定到站点：模板不能带站点，普通画面必须有站点
    if "site_id" in body:
        if user.role_code != "admin":
            raise HTTPException(403, "仅管理员可绑定站点")
        sid = body.get("site_id")
        if sid:
            from ..models import Site
            if not db.query(Site).filter(Site.id == sid).first():
                raise HTTPException(400, f"站点 {sid} 不存在")
            p.site_id = sid
            if p.kind == "template":
                p.kind = "scada"      # 模板一旦绑站，就是该站的实际画面
        else:
            p.site_id = None

    if "locked" in body:
        p.locked = 1 if body.get("locked") else 0

    db.commit()
    return {"ok": True, "id": p.id, "name": p.name, "kind": p.kind,
            "site_id": p.site_id, "locked": p.locked,
            "updated_at": str(p.updated_at or "")}


@router.post("/page/{pid}/duplicate")
def duplicate_page(pid: int, body: dict = None, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """复制画面：整份 json 深拷贝，名称默认「原名-副本」"""
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    src = db.query(Page).filter(Page.id == pid).first()
    if not src:
        raise HTTPException(404, "画面不存在")
    body = body or {}
    name = (body.get("name") or f"{src.name}-副本")[:64]
    p = Page(name=name, kind=src.kind, template_id=None,
             site_id=body.get("site_id", src.site_id), json=src.json)
    db.add(p)
    db.commit()
    return {"ok": True, "id": p.id, "name": p.name}


@router.delete("/page/{pid}")
def delete_page(pid: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """删除画面。有子画面时拒绝，避免把站点画面一起带走。"""
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    # 提示词 10 §4.4：开发阶段固定画面 id=1 是唯一一张，任何入口都不许删掉它
    if pid == FIXED_PAGE_ID:
        raise HTTPException(400, "id=1 是开发阶段唯一的组态画面，不能删除")
    p = db.query(Page).filter(Page.id == pid).first()
    if not p:
        raise HTTPException(404, "画面不存在")
    kids = db.query(Page).filter(Page.template_id == pid).count()
    if kids:
        raise HTTPException(409, f"该画面下还有 {kids} 张子画面，请先删除或解绑子画面")
    db.delete(p)
    db.commit()
    try:
        if os.path.isfile(_thumb_path(pid)):
            os.remove(_thumb_path(pid))      # 画面删了，缩略图文件不能留下
    except OSError:
        pass
    return {"ok": True}


@router.post("/page/instantiate")
def instantiate(body: dict, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """模板实例化：为每个站点复制模板画面，逻辑名 -> 该站实际点位"""
    if user.role_code != "admin":
        raise HTTPException(403, "仅管理员可实例化")
    tpl = db.query(Page).filter(Page.id == body["template_id"],
                                Page.kind == "template").first()
    if not tpl:
        raise HTTPException(404, "模板不存在")
    made = []
    for site_id in body.get("sites", []):
        exists = db.query(Page).filter(Page.template_id == tpl.id,
                                       Page.site_id == site_id).first()
        if exists:
            made.append({"site": site_id, "page_id": exists.id, "exists": True})
            continue
        maps = {}
        for pm in db.query(PointMap).filter(PointMap.template_id == tpl.id,
                                            PointMap.site_id == site_id):
            maps[pm.logical] = pm.point_code
        if not maps:
            # 默认映射：逻辑名 == 点位编码（同名不落表）
            codes = {p.code for p in db.query(Point).filter(Point.site_id == site_id)}
            maps = {c: c for c in codes}
        data = json.loads(tpl.json or "{}")
        for item in data.get("items", []):
            v = item.get("var")
            if v and v in maps:
                item["var"] = maps[v]
            item["site"] = site_id
        p = Page(template_id=tpl.id, site_id=site_id,
                 name=f"{tpl.name}-{site_id}", kind="scada",
                 json=json.dumps(data, ensure_ascii=False))
        db.add(p); db.flush()
        made.append({"site": site_id, "page_id": p.id})
    db.commit()
    return {"ok": True, "created": made}


@router.post("/page/validate")
def validate(body: dict, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """校验画面 JSON：点位是否存在、组件参数是否合法"""
    data = body.get("json", {})
    errs, warns = [], []
    site_id = body.get("site_id")
    codes = {p.code for p in db.query(Point).filter(Point.site_id == site_id)} if site_id else set()
    for i, item in enumerate(data.get("items", [])):
        if not item.get("type"):
            errs.append(f"组件#{i} 缺少 type")
        v = item.get("var")
        if v and site_id and v not in codes:
            warns.append(f"组件#{i}({item['type']}) 引用点位 {v} 不在站点 {site_id}")
    return {"ok": len(errs) == 0, "errors": errs, "warnings": warns}


# —————————————————— 缩略图（P8）——————————————————
# 前端把画布画到 <canvas> 再导出 PNG 上传（比跑 headless chromium 简单得多，200 张也不慢）。
# 存文件不塞 json：一张 400×225 约 30KB，base64 后 40KB，200 张就 8MB。

@router.post("/page/{pid}/thumb")
def put_thumb(pid: int, body: dict, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    p = db.query(Page).filter(Page.id == pid).first()
    if not p:
        raise HTTPException(404, "画面不存在")
    raw = body.get("data") or body.get("png") or ""
    if not isinstance(raw, str) or not raw:
        raise HTTPException(400, "缺少图片数据")
    if raw.startswith("data:"):
        i = raw.find(",")
        if i < 0:
            raise HTTPException(400, "图片数据格式不对")
        raw = raw[i + 1:]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "图片数据不是合法 base64")
    if not data.startswith(PNG_MAGIC):
        raise HTTPException(400, "只收 PNG（缩略图由前端 canvas 导出）")
    if len(data) > THUMB_MAX:
        raise HTTPException(413, "缩略图超过 2MB")
    os.makedirs(THUMB_DIR, exist_ok=True)
    tmp = _thumb_path(pid) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, _thumb_path(pid))
    return {"ok": True, "url": "/api/page/%d/thumb.png?v=%d" % (pid, int(os.path.getmtime(_thumb_path(pid))))}


@router.get("/page/{pid}/thumb.png")
def get_thumb(pid: int):
    """缩略图公开读：<img> 带不了 Authorization 头（与背景图同一套取舍）"""
    path = _thumb_path(pid)
    if not os.path.isfile(path):
        raise HTTPException(404, "缩略图不存在")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


# —————————————————— 一键铺站（P8）——————————————————
# 规则（任务书）：
#   - 复制模板 json，把所有「站点前缀」换成目标站点：S001.LEVEL → S137.LEVEL
#   - 但 @CurrentSite 的表达式（间接连接）**不替换**，它本来就是通用的
# 执行前必须能预览：每站替换了几处、几个点位在目标站不存在。

SITE_PRE = re.compile(r"\b([A-Za-z]\d{3})\.")
TAG_FIND = re.compile(r"\b([A-Za-z]\d{3})\.([A-Za-z0-9_]+)")


def _apply_name(pattern: str, tpl_name: str, site: str, site_name: str = "") -> str:
    s = (pattern or "{name}-{site}").replace("{name}", tpl_name).replace("{site}", site)
    s = s.replace("{site_name}", site_name or site)
    return s[:64]


def _rewrite(node, src_site: str, dst_site: str, stat: dict):
    """深度遍历：字符串里换站点前缀；含 @CurrentSite 的一律不动"""
    if isinstance(node, dict):
        return {k: _rewrite(v, src_site, dst_site, stat) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite(v, src_site, dst_site, stat) for v in node]
    if isinstance(node, str):
        if "@CurrentSite" in node:
            stat["indirect"] += 1
            return node
        if src_site and (src_site + ".") in node:
            stat["replaced"] += node.count(src_site + ".")
            return node.replace(src_site + ".", dst_site + ".")
    return node


def _collect_tags(node, acc: set):
    if isinstance(node, dict):
        for v in node.values():
            _collect_tags(v, acc)
    elif isinstance(node, list):
        for v in node:
            _collect_tags(v, acc)
    elif isinstance(node, str):
        for m in TAG_FIND.finditer(node):
            acc.add(m.group(1) + "." + m.group(2))
    return acc


def _spread_plan(db: Session, pid: int, body: dict):
    src = db.query(Page).filter(Page.id == pid).first()
    if not src:
        raise HTTPException(404, "画面不存在")
    sites = [str(s).strip() for s in (body.get("sites") or []) if str(s).strip()]
    if not sites:
        raise HTTPException(400, "请至少勾选一个站点")
    raw = json.loads(src.json) if src.json else {}
    src_site = src.site_id or ""
    if not src_site:
        # 模板没绑站：用 body.src_site，或从 json 里第一个表达式猜
        src_site = str(body.get("src_site") or "").strip()
        if not src_site:
            tags = _collect_tags(raw, set())
            src_site = next(iter(sorted(tags))).split(".")[0] if tags else ""
    names = {s.id: s.name for s in db.query(Site).filter(Site.id.in_(sites))}
    # 目标站已有点位（一次查完，别在循环里查 200 次）
    codes = {}
    for (sid, code) in db.query(Point.site_id, Point.code).filter(Point.site_id.in_(sites)):
        codes.setdefault(sid, set()).add(code)
    pattern = body.get("name") or "{name}-{site}"
    rows = []
    for sid in sites:
        stat = {"replaced": 0, "indirect": 0}
        data = _rewrite(raw, src_site, sid, stat)
        tags = _collect_tags(data, set())
        mine = {t.split(".", 1)[1] for t in tags if t.split(".", 1)[0] == sid}
        bad = sorted(mine - codes.get(sid, set()))
        rows.append({
            "site": sid, "site_name": names.get(sid, ""),
            "name": _apply_name(pattern, src.name, sid, names.get(sid, "")),
            "replaced": stat["replaced"], "indirect": stat["indirect"],
            "invalid": len(bad), "invalid_tags": bad[:8],
            "exists": bool(db.query(Page).filter(Page.site_id == sid,
                                                 Page.name == _apply_name(pattern, src.name, sid,
                                                                         names.get(sid, ""))).first())
        })
    return src, raw, src_site, rows


@router.post("/page/{pid}/spread/preview")
def spread_preview(pid: int, body: dict, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """预览：每站画面名 / 替换几处 / 几个点位在目标站不存在 —— 执行前先看清楚"""
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    src, _, src_site, rows = _spread_plan(db, pid, body)
    return {"ok": True, "source": {"id": src.id, "name": src.name, "site": src_site,
                                   "kind": src.kind},
            "rows": rows,
            "summary": {"sites": len(rows),
                        "replaced": sum(r["replaced"] for r in rows),
                        "invalid": sum(r["invalid"] for r in rows),
                        "exists": sum(1 for r in rows if r["exists"])}}


@router.post("/page/{pid}/spread")
def spread(pid: int, body: dict, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    """执行铺站：每站生成一张独立画面（站点之间有差异时用这条；完全同构的用组件模板）"""
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无组态编辑权限")
    src, raw, src_site, rows = _spread_plan(db, pid, body)
    overwrite = bool(body.get("overwrite"))
    made = []
    for row in rows:
        sid = row["site"]
        stat = {"replaced": 0, "indirect": 0}
        data = _rewrite(raw, src_site, sid, stat)
        old = None
        if overwrite:
            old = db.query(Page).filter(Page.site_id == sid, Page.name == row["name"]).first()
        if old:
            old.json = json.dumps(data, ensure_ascii=False)
            old.template_id = src.id if src.kind in ("template", "screen") else old.template_id
            made.append({"site": sid, "page_id": old.id, "name": old.name, "updated": True})
            continue
        p = Page(name=row["name"], kind="scada", site_id=sid,
                 template_id=src.id if src.kind in ("template", "screen") else None,
                 json=json.dumps(data, ensure_ascii=False))
        db.add(p)
        db.flush()
        made.append({"site": sid, "page_id": p.id, "name": p.name, "updated": False})
    db.commit()
    return {"ok": True, "created": made, "count": len(made)}
