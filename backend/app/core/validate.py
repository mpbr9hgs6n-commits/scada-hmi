# -*- coding: utf-8 -*-
"""参数校验与转义（安全整改 02）

规矩：
1. 能用白名单就用白名单，不做"过滤危险字符"那种黑名单（永远漏）；
2. 字符串进 SQL 前必须再过一道转义函数，双保险；
3. 数值参数先按字符串收，自己判断范围和格式，越界一律 400——
   直接 int() 遇到 "abc" 会 500，遇到 "1e9" 会把库拖死。
"""
import re
from fastapi import HTTPException

# 站点编号：S001 这类，字母数字下划线短横
SITE_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
# 点位编码：AI0483 / LEVEL / PUMP1_RUN
POINT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
# 降采样间隔：1m 5m 1h 1d（TDengine interval() 的合法写法）
INTERVAL_RE = re.compile(r"^\d{1,3}[smhd]$")
# 纯数字串（用来替代 int() 直接吞）
DIGITS_RE = re.compile(r"^\d{1,9}$")


def bad(msg: str):
    raise HTTPException(400, msg)


def require_site(v: str) -> str:
    if not isinstance(v, str) or not SITE_RE.match(v):
        bad("site 参数非法（只允许字母、数字、下划线、短横，1~16 位）")
    return v


def require_point(v: str) -> str:
    if not isinstance(v, str) or not POINT_RE.match(v):
        bad("point 参数非法（只允许字母、数字、下划线、点、短横，1~32 位）")
    return v


def require_int(v, lo: int, hi: int, name: str, default=None):
    """按字符串收，自己判断：非数字、越界一律 400"""
    if v is None or v == "":
        return default
    s = str(v).strip()
    if not DIGITS_RE.match(s):
        bad(f"{name} 必须是整数")
    n = int(s)
    if n < lo or n > hi:
        bad(f"{name} 超出范围 [{lo}, {hi}]")
    return n


def require_interval(v: str):
    if v is None or v == "":
        return None
    if not INTERVAL_RE.match(str(v)):
        bad("interval 只允许形如 1m / 5m / 1h / 1d")
    return str(v)


def require_ts(v: str, name: str):
    """时间参数：必须是 ISO 格式，转成 datetime；非法给 400 而不是 500"""
    import datetime as dt
    if v is None or v == "":
        return None
    try:
        return dt.datetime.fromisoformat(str(v))
    except Exception:
        bad(f"{name} 必须是 ISO 时间，如 2026-11-07T12:00:00")


def td_str(s: str) -> str:
    """TDengine 字符串字面量转义（REST 不支持绑定参数，只能转义 + 白名单双保险）"""
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


# ============================================================================
# 点位校验（提示词 09 第 6 节：12 条规则，三个录入入口共用这一份）
#   单个新增 / 批量生成 / Excel-CSV 导入 / 修改，全部先过 validate_point。
# 返回 (errors, warnings)：
#   errors  —— [{row, field, msg}]，非空就拒绝落库
#   warnings—— [str]，只提示不阻断（如"1000 点 @1s 可能超出 PLC 能力"）
# ============================================================================

from .addr import (valid_addr, parse_addr, check_alignment, readonly_area,
                   addr_span, is_int_dtype, type_size, s7_width_mismatch)

# 提示词 2.2：编码只允许大写字母/数字/下划线（站内唯一由调用方查库）
# 编码字符集：允许大小写。用户 2026-11 明确「小写不转大写」，
# 而现场点表本身的编码就是小写（HES_U1_AI_F01_Offset 这类），
# 只允许大写会让整份点表一个都导不进去。
CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
DTYPE_SET = {"bool", "byte", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"}

# 各品牌 PLC 编程软件的数据类型写法 → 平台内部标准名。
# 用户会按西门子/三菱的写法填（REAL / WORD / DWORD / BIT...），
# 这些必须自动映射，不能当成非法值拒绝。
DTYPE_ALIAS = {
    "real": "float32", "lreal": "float64", "double": "float64", "float": "float32",
    "word": "uint16", "dword": "uint32", "int": "int16", "dint": "int32",
    "sint": "byte", "usint": "byte", "bit": "bool", "boolean": "bool",
    "byte": "byte", "string": "string",
}


def norm_dtype(v) -> str:
    """dtype 规范化：先查 PLC 写法别名表，再回落小写。"""
    s0 = str(v or "").strip()
    if not s0:
        return "float32"
    low = s0.lower()
    return DTYPE_ALIAS.get(low, low)
BYTE_ORDERS = {"ABCD", "CDAB", "BADC", "DCBA"}


def validate_point(p: dict, site: dict, others: list, row: int = 1):
    """校验一个点位。

    p       点位字段（code/name/addr/dtype/byte_order/bit_offset/poll_ms/…）
    site    所属站点（plc_protocol/plc_ip/plc_port/rack/slot/slave_id…）
    others  同站点其余点位 [{code, addr, dtype}]，用于唯一性与重叠校验
    row     行号（批量/导入预览里标红用；单个新增传 1）
    """
    errors, warnings = [], []

    def err(field, msg):
        errors.append({"row": row, "field": field, "msg": msg})

    # 编码：用户常在编码后面加中文注释（如 HES_U1_AI_P01_Offset(补偿）），
    # 只保留字母/数字/下划线，其余剥掉；不强制转大写（用户 2026-11 明确要求）。
    code = re.sub(r"[^A-Za-z0-9_]", "", str(p.get("code") or "").strip())
    # 地址：用户会写成 "VD 5518"、"M 5.2" 这种带空格的形式，去掉所有空白
    addr = re.sub(r"\s+", "", str(p.get("addr") or "").strip())
    # 数据类型：支持 PLC 编程软件写法（REAL/WORD/DWORD/BIT...）
    dtype = norm_dtype(p.get("dtype"))
    proto = (site.get("plc_protocol") or site.get("protocol") or "").lower()

    # 把规范化结果写回 p：预览与落库都要用干净值，不能只有校验时干净
    if "code" in p:
        p["code"] = code
    if "addr" in p:
        p["addr"] = addr
    if "dtype" in p or dtype:
        p["dtype"] = dtype

    # 2 编码字符集
    if not code:
        err("code", "点位编码不能为空")
    elif not CODE_RE.match(code):
        err("code", f"编码 {code} 只能字母/数字/下划线（1~32 位）")
    # 1 站内唯一
    if code and any(str(o.get("code") or "").upper() == code for o in others):
        err("code", f"点位编码 {code} 已存在")
    # dtype 合法性（不在 12 条里，但脏值必须拦）
    if dtype not in DTYPE_SET:
        err("dtype", f"数据类型 {dtype} 不在 {sorted(DTYPE_SET)} 里")
    # 3 地址格式
    ok, hint = valid_addr(proto, addr)
    if not addr:
        err("addr", "地址不能为空")
    elif not ok:
        err("addr", f"{addr} 不是 {proto} 的合法地址（示例：{hint}）")
    else:
        try:
            parse_addr(proto, addr)
        except ValueError as e:
            err("addr", str(e))
        # 4 类型与地址对齐
        if not any(x["field"] == "addr" for x in errors):
            align_ok, align_msg = check_alignment(proto, addr, dtype)
            if not align_ok:
                err("addr", align_msg)
            # 4b 宽度必须与地址后缀一致（VB=1 / VW=2 / VD=4）
            # 用户明确要求：写了字节就严格按字节寻址，类型对不上直接报错，不替他改写
            wmsg = s7_width_mismatch(proto, addr, dtype)
            if wmsg:
                err("dtype", wmsg)
        # 6 可写区：输入区/输出区一律只读（用户 2026-11 要求）
        #   不报错，直接忽略点表里的 rw 设置并置 0，只给一条警告说明改了什么。
        #   覆盖 S7 的 I/Q、三菱的 X/Y、Modbus 的 DI/IR/C。
        if readonly_area(proto, addr) and int(p.get("rw") or 0) == 1:
            p["rw"] = 0
            warnings.append(f"{addr} 属于只读区（输入/输出区），已自动设为只读")
    # 5 同站点地址不重叠
    if addr and not any(x["field"] == "addr" and addr in x["msg"] for x in errors):
        try:
            area, s0, e0 = addr_span(proto, addr, dtype)
            for o in others:
                if not o.get("addr"):
                    continue
                try:
                    a2, s2, e2 = addr_span(proto, o["addr"], str(o.get("dtype") or "float32"))
                except ValueError:
                    continue
                if a2 == area and s0 < e2 and s2 < e0:
                    err("addr", f"与点位 {o.get('code')}({o.get('addr')}) 地址重叠")
                    break
        except ValueError:
            pass   # 格式错已在上面报过
    # 6.5 string 的提醒（变长类型，重叠校验只能按 1 字节保守估）
    if dtype == "string" and addr and not errors:
        warnings.append(
            f"{addr} 是字符串类型：变长（实际可能占 10~20 字节），"
            "重叠校验按 1 字节保守估，请给它单独留一段连续地址，不要和后面的点位挨着放")

    # 7 poll_ms 范围
    poll = p.get("poll_ms")
    if poll is not None:
        try:
            poll = int(poll)
            if not 100 <= poll <= 60000:
                err("poll_ms", "采集周期必须在 100~60000ms")
        except (TypeError, ValueError):
            err("poll_ms", "采集周期必须是整数毫秒")
    # 8 站点超时已内置（3 秒），不再有「周期不能小于站点超时」这条校验：
    #   站点参数里已经没有 timeout_ms 这一项了，用户也配不了。
    # 9 周期×点位数 超协议能力 → 警告不阻断
    n_pts = len(others) + 1
    eff_poll = int(poll or 1000)   # 站点级采集周期已内置，只看点位自己的 poll_ms
    if n_pts >= 500 and eff_poll <= 1000:
        warnings.append(f"该站 {n_pts} 点 @ {eff_poll}ms 可能超出 PLC 响应能力，建议加大周期或减少点位")
    # 10 量程
    smin, smax = p.get("scale_min"), p.get("scale_max")
    if smin is not None and smax is not None and float(smin) >= float(smax):
        err("scale_max", "量程下限必须小于上限")
    # 11 小数位
    dec = p.get("decimals")
    if dec is not None:
        try:
            if not 0 <= int(dec) <= 4:
                err("decimals", "小数位必须在 0~4")
        except (TypeError, ValueError):
            err("decimals", "小数位必须是 0~4 的整数")
    # 12 位偏移仅整数类型
    bo = p.get("bit_offset")
    if bo is not None:
        if not is_int_dtype(dtype):
            err("bit_offset", "浮点类型不能用位偏移")
        elif not 0 <= int(bo) <= 15:
            err("bit_offset", "位偏移必须在 0~15")
    # byte_order 取值
    if p.get("byte_order") and str(p["byte_order"]).upper() not in BYTE_ORDERS:
        err("byte_order", "字节序只能是 ABCD / CDAB / BADC / DCBA")
    # string 类型不参与采集合并，也不允许 rw
    if dtype == "string":
        warnings.append("string 类型本期只录入不采集（地址不进采集块）")
    return errors, warnings

