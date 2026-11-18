"""组件模板（Faceplate）与值列表（P8）

官方依据：
- 4.6.1 P442 类型/实例模型：类型里画对象，实例是「类型的使用地点」
- 4.6.2.5 P453 接口变量：类型内部用 @PV / @RUN 引用，实例上绑定实际变量
- 4.7.1 / 4.7.2 P496/P500 文本列表 / 图形列表

两条硬约束（写在这里，防止后人改回拷贝）：
1) 实例只存 fpt_id + bindings，**不拷贝模板 json** —— 拷贝了「改模板同步变」就失效
2) 接口变量名不允许与 @CurrentSite 冲突（那是运行时的站点关键字，不是接口变量）
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Faceplate, Page, User, ValueList

router = APIRouter(prefix="/api", tags=["fpt"])

EDIT_ROLES = ("admin", "operator")
IFACE_TYPES = ("real", "bool", "int", "string")
RESERVED = ("CurrentSite",)          # 运行时关键字，不能当接口变量
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,15}$")


def _role_ok(user: User, what: str = "组态编辑"):
    if user.role_code not in EDIT_ROLES:
        raise HTTPException(403, "无%s权限" % what)


def _loads(raw, dflt):
    try:
        v = json.loads(raw) if raw else dflt
        return v if isinstance(v, type(dflt)) else dflt
    except Exception:
        return dflt


def _norm_iface(raw):
    """接口变量归一化 + 校验：名字唯一、字母开头、类型合法、不与运行时关键字冲突"""
    out = []
    seen = set()
    for t in (raw or []):
        if not isinstance(t, dict):
            continue
        nm = str(t.get("name") or "").strip()
        if not nm:
            raise HTTPException(400, "接口变量名不能为空")
        if not NAME_RE.match(nm):
            raise HTTPException(400, "接口变量名「%s」不合法：字母或下划线开头，最长 16 位" % nm)
        if nm in RESERVED:
            raise HTTPException(400, "「%s」是运行时关键字，不能作接口变量名" % nm)
        if nm in seen:
            raise HTTPException(400, "接口变量名重复：%s" % nm)
        seen.add(nm)
        tp = str(t.get("type") or "real").lower()
        if tp not in IFACE_TYPES:
            raise HTTPException(400, "接口变量「%s」的类型必须是 real/bool/int/string" % nm)
        out.append({"name": nm, "type": tp,
                    "default": t.get("default", 0 if tp != "string" else ""),
                    "desc": str(t.get("desc") or "")[:64]})
    return out


def _count_items(raw):
    items = _loads(raw, {}).get("items")
    return len(items) if isinstance(items, list) else 0


# —————————————————— 组件模板 ——————————————————

@router.get("/fpt")
def list_fpt(full: int = 0, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """full=1 时带上 json —— 编辑器/只读页一次拉全，渲染实例时不必逐个请求"""
    rows = db.query(Faceplate).order_by(Faceplate.id).all()
    out = []
    for f in rows:
        row = {"id": f.id, "name": f.name, "w": f.w, "h": f.h, "locked": f.locked,
               "objects": _count_items(f.json),
               "iface": _loads(f.iface, []),
               "updated_at": str(f.updated_at or "")}
        if full:
            row["json"] = _loads(f.json, {})
            row["iface"] = _loads(f.iface, [])
        out.append(row)
    return {"items": out}


@router.get("/fpt/{fid}")
def get_fpt(fid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    f = db.query(Faceplate).filter(Faceplate.id == fid).first()
    if not f:
        raise HTTPException(404, "组件模板不存在")
    data = _loads(f.json, {})
    return {"id": f.id, "name": f.name, "w": f.w, "h": f.h, "locked": f.locked,
            "iface": _loads(f.iface, []),
            "json": {"width": data.get("width", f.w), "height": data.get("height", f.h),
                     "bg": data.get("bg", "transparent"),
                     "items": data.get("items") if isinstance(data.get("items"), list) else []}}


@router.post("/fpt")
def save_fpt(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role_ok(user)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "组件模板名称不能为空")
    if len(name) > 64:
        raise HTTPException(400, "组件模板名称最长 64 个字符")
    iface = _norm_iface(body.get("iface"))
    data = body.get("json") or {}
    w = int(body.get("w") or data.get("width") or 200)
    h = int(body.get("h") or data.get("height") or 200)
    if not (20 <= w <= 4000 and 20 <= h <= 4000):
        raise HTTPException(400, "组件模板尺寸要在 20~4000 之间")

    if body.get("id"):
        f = db.query(Faceplate).filter(Faceplate.id == body["id"]).first()
        if not f:
            raise HTTPException(404, "组件模板不存在")
        if f.locked:
            raise HTTPException(403, "组件模板已锁定，先解锁再改")
    else:
        f = Faceplate()
        db.add(f)
    f.name = name
    f.w = w
    f.h = h
    f.json = json.dumps(data, ensure_ascii=False)
    f.iface = json.dumps(iface, ensure_ascii=False)
    db.commit()
    return {"ok": True, "id": f.id, "name": f.name, "w": f.w, "h": f.h, "iface": iface}


@router.put("/fpt/{fid}")
def update_fpt(fid: int, body: dict, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    _role_ok(user)
    f = db.query(Faceplate).filter(Faceplate.id == fid).first()
    if not f:
        raise HTTPException(404, "组件模板不存在")
    if "name" in body:
        nm = (body.get("name") or "").strip()
        if not nm:
            raise HTTPException(400, "组件模板名称不能为空")
        f.name = nm[:64]
    if "iface" in body:
        f.iface = json.dumps(_norm_iface(body["iface"]), ensure_ascii=False)
    if "locked" in body:
        f.locked = 1 if body.get("locked") else 0
    db.commit()
    return {"ok": True, "id": f.id, "name": f.name, "locked": f.locked}


def _uses_fpt(node, fid):
    """画布 json 里有没有引用这个模板（组合可以嵌套，要递归）"""
    if isinstance(node, dict):
        if node.get("type") == "faceplate":
            try:
                if int(node.get("fptId") or 0) == fid:
                    return True
            except (TypeError, ValueError):
                pass
        for v in node.values():
            if _uses_fpt(v, fid):
                return True
    elif isinstance(node, list):
        for v in node:
            if _uses_fpt(v, fid):
                return True
    return False


@router.delete("/fpt/{fid}")
def delete_fpt(fid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _role_ok(user)
    f = db.query(Faceplate).filter(Faceplate.id == fid).first()
    if not f:
        raise HTTPException(404, "组件模板不存在")
    # 被画面引用就不许删（否则实例渲染成空框，用户看不出为什么）。
    # 用解析 json 而不是 LIKE '%"fptId": 1%'：后者一来会把 fptId 12 当成 1，
    # 二来 % 在 Python 字符串格式化里是占位符，写成 '%%"fptId": %d%%' % fid 会直接抛
    # ValueError（这个坑真的踩过，删模板恒 500）。
    used = 0
    for _pid, raw in db.query(Page.id, Page.json).all():
        try:
            j = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        if _uses_fpt(j, fid):
            used += 1
    if used:
        raise HTTPException(409, "有 %d 张画面在用这个组件模板，先删实例再删模板" % used)
    db.delete(f)
    db.commit()
    return {"ok": True}


# —————————————————— 文本列表 / 图形列表 ——————————————————

def _norm_items(kind, items):
    out = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        v = it.get("value")
        try:
            v = float(v)
            v = int(v) if v == int(v) else v
        except Exception:
            raise HTTPException(400, "列表项 value 必须是数字")
        if kind == "graph":
            img = str(it.get("image") or "").strip()
            if not img:
                raise HTTPException(400, "图形列表每项都要有图片地址")
            out.append({"value": v, "image": img})
        else:
            out.append({"value": v, "text": str(it.get("text") if it.get("text") is not None else "")[:64]})
    return out


@router.get("/valuelists")
def list_valuelists(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ValueList).order_by(ValueList.name).all()
    return {"items": [{"id": r.id, "name": r.name, "kind": r.kind,
                       "items": _loads(r.items, []),
                       "updated_at": str(r.updated_at or "")} for r in rows]}


@router.post("/valuelist")
def save_valuelist(body: dict, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    _role_ok(user)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "列表名称不能为空")
    kind = body.get("kind") or "text"
    if kind not in ("text", "graph"):
        raise HTTPException(400, "列表类型只能是 text 或 graph")
    items = _norm_items(kind, body.get("items"))
    if body.get("id"):
        row = db.query(ValueList).filter(ValueList.id == body["id"]).first()
    else:
        row = db.query(ValueList).filter(ValueList.name == name).first()
        if row:
            raise HTTPException(400, "列表名「%s」已存在" % name)
    if not row:
        row = ValueList()
        db.add(row)
    row.name = name
    row.kind = kind
    row.items = json.dumps(items, ensure_ascii=False)
    db.commit()
    return {"ok": True, "id": row.id, "name": row.name, "kind": row.kind, "items": items}


@router.delete("/valuelist/{vid}")
def delete_valuelist(vid: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _role_ok(user)
    row = db.query(ValueList).filter(ValueList.id == vid).first()
    if not row:
        raise HTTPException(404, "列表不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/valuelist/export")
def export_valuelists(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ValueList).order_by(ValueList.name).all()
    return {"lists": [{"name": r.name, "kind": r.kind, "items": _loads(r.items, [])} for r in rows]}


@router.post("/valuelist/import")
def import_valuelists(body: dict, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    _role_ok(user)
    lists = body.get("lists")
    if not isinstance(lists, list):
        raise HTTPException(400, "导入内容要形如 {\"lists\":[…]}")
    n_new = n_upd = 0
    for it in lists:
        nm = str((it or {}).get("name") or "").strip()
        if not nm:
            continue
        kind = (it.get("kind") or "text")
        if kind not in ("text", "graph"):
            raise HTTPException(400, "列表「%s」的类型不合法" % nm)
        items = _norm_items(kind, it.get("items"))
        row = db.query(ValueList).filter(ValueList.name == nm).first()
        if row:
            n_upd += 1
        else:
            row = ValueList(name=nm)
            db.add(row)
            n_new += 1
        row.kind = kind
        row.items = json.dumps(items, ensure_ascii=False)
    db.commit()
    return {"ok": True, "created": n_new, "updated": n_upd}
