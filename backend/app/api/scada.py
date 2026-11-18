"""组态运行支持接口（P4）

两个接口，都只为「变量关联」服务：
1) GET /api/devices?site=S001   变量选择器的第二级（站点 → 设备 → 点位）
2) POST /api/scada/resolve      批量解析变量名 → 是否存在 / 当前值 / 质量码
   UI 的「200 站点求值预览」一次要问 200 个变量名，逐个请求会把后端打爆，
   所以必须批量：一次 SQL + 每站一次 Redis HGETALL。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..db import get_db, redis_client
from ..models import Point, User
from ..auth import get_current_user, check_site_permission, site_scope_ids
from ..core.realtime import hget_all

router = APIRouter(prefix="/api", tags=["scada"])

MAX_TAGS = 500


# 02：GET /api/devices 挪到了 api/devices.py（设备管理页与变量树共用一个路由：
#     带 site 参数 = 变量树老行为，不带 = 设备管理列表。这里不能再定义一遍，
#     不然后注册的被前一个吃掉，设备管理页就永远 400「site 必填」）。

@router.post("/scada/oplog")
async def operator_message(body: dict, request: Request, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """输出操作员消息（P5 动作里的"输出操作员消息"勾选项）

    跟写点位分开一个接口：打开画面、切颜色这类动作没有点位可写，
    但甲方验收一定问"谁在什么时候动了什么"，所以消息也必须落审计。
    """
    from ..models import OpLog
    site = str(body.get("site") or "")
    if site:
        check_site_permission(user, site, db)
    msg = str(body.get("msg") or "").strip()[:64]
    if not msg:
        raise HTTPException(400, "msg 必填")
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else ""))
    db.add(OpLog(username=user.username, site_id=site or None,
                 point_code=str(body.get("point") or "")[:32] or None,
                 action="msg", old_val=None, new_val=msg, ip=ip, result="ok"))
    db.commit()
    return {"ok": True}


@router.post("/scada/resolve")
async def resolve_tags(body: dict, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """批量解析：["S001.LEVEL", "S002.LEVEL", ...] → 每个的存在性 + 当前值

    返回与入参同序，缺项用 found=false 补位（前端按顺序标红即可，不用自己对齐）。
    """
    tags = body.get("tags") or []
    if not isinstance(tags, list) or not tags:
        raise HTTPException(400, "tags 必填且不能为空")
    if len(tags) > MAX_TAGS:
        raise HTTPException(400, f"一次最多解析 {MAX_TAGS} 个变量名")

    # 先拆成 (site, code)，非法格式直接当不存在
    parsed = []
    for t in tags:
        s = str(t or "").strip()
        if "." not in s:
            parsed.append((s, None, None))
            continue
        site, code = s.split(".", 1)
        parsed.append((s, site, code))

    scope = site_scope_ids(user, db)
    sites = sorted({p[1] for p in parsed if p[1]})
    allowed = {}
    for s in sites:
        try:
            check_site_permission(user, s, db)
            allowed[s] = True
        except HTTPException:
            allowed[s] = False

    # 一次查出所有需要的点位（按站点分组，避免 N 次查询）
    found = {}
    for s in sites:
        if not allowed.get(s):
            continue
        codes = [p[2] for p in parsed if p[1] == s]
        if not codes:
            continue
        rows = (db.query(Point)
                  .filter(Point.site_id == s, Point.code.in_(codes))
                  .all())
        for r in rows:
            found[(s, r.code)] = r

    # 每站一次 Redis 读实时值（只读，不查 TDengine）
    vals = {}
    for s in sites:
        if not allowed.get(s):
            continue
        try:
            vals[s] = await hget_all(redis_client, s)
        except Exception:
            vals[s] = {}

    out = []
    for tag, site, code in parsed:
        if not site:
            out.append({"tag": tag, "found": False, "reason": "bad_name",
                        "msg": "变量名要写成 站点.点位，如 S001.LEVEL"})
            continue
        if not allowed.get(site):
            out.append({"tag": tag, "found": False, "reason": "no_perm",
                        "msg": "无权访问站点 " + site})
            continue
        p = found.get((site, code))
        if not p:
            out.append({"tag": tag, "found": False, "reason": "not_found",
                        "site": site, "code": code, "msg": "点位不存在"})
            continue
        v = vals.get(site, {}).get(code)
        dec = p.decimals if p.decimals is not None else 2
        out.append({
            "tag": tag, "found": True, "site": site, "code": code,
            "name": p.name, "unit": p.unit, "dtype": p.dtype,
            "decimals": dec, "rw": p.rw,
            "scale_min": p.scale_min, "scale_max": p.scale_max,
            "value": (round(v["val"], dec) if v else None),
            "q": (v["q"] if v else 0),
            "ts": (v["ts"] if v else 0),
        })
    return {"items": out}
