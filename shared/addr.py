# -*- coding: utf-8 -*-
"""全系统唯一的地址解析与类型长度（提示词 09 第 2.3 / 第 7 节）。

仓库里只有这一个文件定义地址规则；构建时分别拷进两个镜像：
  - backend  → /app/app/core/addr.py
  - gateway  → /app/addr.py
采集器、点位校验、批量生成、导入预览全部 import 这里。
禁止在任何别处再写一份解析（含前端——前端只做提示，真校验在后端）。

统一返回形状 parse_addr(protocol, addr) -> (area, db, off, size, bit)：
  area  区域字母（s7: V/M/I/Q/DB；mc: D/M/X/Y…；modbus: HR/C/DI/IR；fins: D/W/CIO…）
  db    DB 号（仅 s7 的 DBn.DBx 用，其余 0）
  off   区域内偏移（s7=字节；mc 字软元件=编号、位软元件=位编号；modbus=寄存器/线圈号）
  size  该 dtype 占的字节数（bool 位地址=1）
  bit   位号（VD1000 这种非位地址为 None）

addr 写法（按品牌原编程软件，不做转换）：
  s7   (S7-200 SMART)  V1000.0  M10.1  I0.0  Q0.0  VW1000  VD1000
  s7   (1200/1500)     DB1.DBX0.0  DB1.DBW0  DB1.DBD0
  mc_1e/mc_3e (FX)     M8013  X0  Y0  D1000（32 位占 2 字）
  modbus_tcp           4x10001 / HR10001 / 十进制偏移 8 / 0x00001（线圈）
  fins  (欧姆龙)        W0.00  D100
"""
import re

# ---------------- 类型长度（唯一一份；校验、块合并、写入全用它） ----------------
_DTYPE_SIZE = {"bool": 1, "byte": 1, "int16": 2, "uint16": 2, "int32": 4, "uint32": 4,
               "float32": 4, "float64": 8, "string": 0}


def type_size(dtype) -> int:
    """dtype 占的字节数；string 返回 0（变长，不参与地址合并/对齐）"""
    return _DTYPE_SIZE.get(str(dtype).lower(), 2)


def is_int_dtype(dtype) -> bool:
    # byte（无符号 8 位）也是整数：允许配 bit_offset 从字节里取某一位
    return str(dtype).lower() in ("bool", "byte", "int16", "uint16", "int32", "uint32")


# ---------------- 地址正则（与前端 protocolSchema.js 同一套文案与规则） ----------------
# 2026-11-09 起统一大小写不敏感（现场常手输 vd1000/x10），校验前先 upper。
ADDR_RULES = {
    "s7": {"re": r"^(DB\d+\.DB[XBWD]\d+(?:\.\d+)?|V[BWD]?\d+(?:\.\d+)?|M[BWD]?\d+(?:\.\d+)?|[IQ][BWD]?\d+(?:\.\d+)?)$",
           "hint": "VD1000 / VW100 / VB0 / V1000.3 / M10.1 / IW0 / QW2 / DB1.DBW0"},
    "mc_1e": {"re": r"^([DMRXYSTCLFVBWZ]\d+|W[0-9A-Fa-f]{1,3}|ZR\d+)$",
              "hint": "D1018 / M100 / X10 / Y20 / W1E0 / ZR100"},
    "mc_3e": {"re": r"^([DMRXYSTCLFVBWZ]\d+|W[0-9A-Fa-f]{1,3}|ZR\d+)$",
              "hint": "D1018 / M100 / X10 / Y20 / W1E0 / ZR100"},
    "mc": {"re": r"^([DMRXYSTCLFVBWZ]\d+|W[0-9A-Fa-f]{1,3}|ZR\d+)$",
           "hint": "D1018 / M100 / X10 / Y20 / W1E0 / ZR100"},
    "fins": {"re": r"^([DCWATE]\d+|CIO\d+)$", "hint": "D100 / CIO10 / W20 / A100"},
    "modbus_tcp": {"re": r"^(\d+|[34]\d{4}|[0-9]\d{4}|HR\d+|0[xX][0-9A-Fa-f]+)$",
                   "hint": "HR8 / 十进制偏移 8 / 40001 式 / 0x00001（线圈）"},
    "modbus_rtu": {"re": r"^(\d+|[34]\d{4}|[0-9]\d{4}|HR\d+|0[xX][0-9A-Fa-f]+)$",
                   "hint": "HR8 / 十进制偏移 8 / 40001 式 / 0x00001（线圈）"},
    "opcua": {"re": r"^ns=\d+;[isgb]=.+$", "hint": "ns=2;s=Tank.Level"},
}


def valid_addr(protocol: str, addr: str):
    """返回 (是否合法, 提示文案)。协议没规则的（opcua 由后端正则管）默认放行。"""
    rule = ADDR_RULES.get((protocol or "").lower())
    if not rule:
        return True, ""
    ok = re.match(rule["re"], (addr or "").strip().upper()) is not None
    return ok, rule["hint"]


# ---------------- MC 软元件分类（FX：字按字读，位按位读） ----------------
MC_WORD_DEVS = set("DWRZTC")   # D/W/R/Z：数据寄存器；T/C：当前值按字读
MC_BIT_DEVS = set("XYMLSB")    # X/Y/M/L/S/B：位软元件
# X/Y 是八进制，但 1E 帧位读也按编号发、由 PLC 端解释——平台不拆八进制

# ---------------- 各协议只读区（rw=1 的点位不许落在这些区） ----------------
# 只读区（用户 2026-11 要求：输入区 + 输出区一律仅读取，程序忽略点表里的 rw 设置）
#   S7      I 输入区 / Q 输出区
#   三菱 MC  X 输入 / Y 输出
#   Modbus  DI 离散输入 / IR 输入寄存器 / C 线圈（对应输出区）
#   欧姆龙 FINS 的 CIO 区读写混合，没有纯输入区，保持空集
READONLY_AREAS = {
    "s7": {"I", "Q"},
    "mc_1e": {"X", "Y"}, "mc_3e": {"X", "Y"}, "mc": {"X", "Y"},
    "modbus_tcp": {"DI", "IR", "C"},
    "modbus_rtu": {"DI", "IR", "C"},
    "fins": set(),
}

# S7 地址后缀 → 占用字节数。空串表示"没写后缀"，默认按字（V1000 = VW1000）。
# 这是**地址本身的语义**，不能拿 dtype 去覆盖它 —— 见 s7_explicit_kind 的说明。
S7_KIND_SIZE = {"": 2, "B": 1, "W": 2, "D": 4}
_S7_KIND_SIZE = S7_KIND_SIZE


def s7_explicit_kind(a: str) -> str:
    """返回地址里**显式写出来的**宽度字母：'' 表示没写，否则 'B'/'W'/'D'。

    为什么需要它：V1000 / VW1000 / VD1000 在协议上是三种不同宽度的寻址。
    如果用户在 VB（1 字节）上配了 uint16（2 字节），两者是矛盾的 ——
    该报错让他改，而不是我们按 dtype 悄悄读 2 个字节（那样会踩到下一个字节的数据，
    现场表现为"这个点读出来总是错的，但看地址又没错"）。
    """
    if not a:
        return ""
    m = re.match(r"^DB\d+\.DB([XBWD])\d+", a)
    if m:
        return m.group(1)
    m = re.match(r"^[VMIQ]([BWD]?)\d+", a)
    if m:
        return m.group(1)
    return ""


def _parse_s7(a: str):
    m = re.match(r"^DB(\d+)\.DB([XBWD])(\d+)(?:\.(\d+))?$", a)
    if m:
        db, kind, off, bit = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        size = 1 if bit is not None else _S7_KIND_SIZE[kind]
        return "DB", db, off, size, int(bit) if bit is not None else None
    m = re.match(r"^([VMIQ])([BWD]?)(\d+)(?:\.(\d+))?$", a)
    if not m:
        raise ValueError(f"无法解析 S7 地址 {a}")
    area, kind, off, bit = m.group(1), m.group(2) or "W", int(m.group(3)), m.group(4)
    size = 1 if bit is not None else _S7_KIND_SIZE[kind]
    return area, 1 if area == "V" else 0, off, size, int(bit) if bit is not None else None


def _parse_mc(a: str):
    """D1018 → ('D', 0, 1018, 2, None)；M100 → ('M', 0, 100, 1, None)
    off 直接用软元件编号（字=字编号、位=位编号），是否字软元件看 area。"""
    m = re.match(r"^([A-Z]+)(\d+)$", a)
    if not m:
        raise ValueError(f"无法解析 MC 地址 {a}")
    dev, num = m.group(1), int(m.group(2))
    if len(dev) != 1:
        raise ValueError(f"MC 地址软元件名只支持单字母，收到 {dev}")
    if dev in MC_WORD_DEVS:
        return dev, 0, num, 2, None
    if dev in MC_BIT_DEVS:
        return dev, 0, num, 1, None
    raise ValueError(f"MC 不支持的软元件 {dev}")


def _parse_modbus(a: str):
    """HR123 / 123 / 40001~49999（保持寄存器）→ ('HR', 0, 偏移, size, None)
    0x00001（线圈）→ ('C', 0, 线圈号, 1, None)
    3xxxx（输入寄存器）→ ('IR', 0, 偏移, size, None)
    1xxxx（离散输入）→ ('DI', 0, 序号, 1, None)"""
    if a.upper().startswith("HR"):
        return "HR", 0, int(a[2:]), 2, None
    if a.lower().startswith("0x"):
        n = int(a, 16)
        return "C", 0, n - 1, 1, None          # 0x00001 → 线圈 0
    if a.startswith("4") and len(a) == 5:
        return "HR", 0, int(a) - 40001, 2, None
    if a.startswith("3") and len(a) == 5:
        return "IR", 0, int(a) - 30001, 2, None
    if a.startswith("1") and len(a) == 5:
        return "DI", 0, int(a) - 10001, 1, None
    return "HR", 0, int(a), 2, None             # 裸十进制偏移 = 保持寄存器


def _parse_fins(a: str):
    m = re.match(r"^(CIO|[DCWATE])(\d+)(?:\.(\d{1,2}))?$", a)
    if not m:
        raise ValueError(f"无法解析 FINS 地址 {a}")
    bit = m.group(3)
    return m.group(1), 0, int(m.group(2)), 1 if bit else 2, \
        int(bit) if bit else None


def parse_addr(protocol: str, addr: str):
    """统一地址解析入口（全系统唯一实现，见模块注释）。返回 5 元组，异常 ValueError。"""
    p = (protocol or "").lower()
    a = (addr or "").strip().upper()
    if p == "s7":
        return _parse_s7(a)
    if p in ("mc", "mc_1e", "mc_3e"):
        return _parse_mc(a)
    if p in ("modbus_tcp", "modbus_rtu"):
        return _parse_modbus(a)
    if p == "fins":
        return _parse_fins(a)
    raise ValueError(f"暂不支持解析 {protocol} 的地址")


def s7_width_mismatch(protocol: str, addr: str, dtype: str) -> str:
    """S7 地址后缀（VB/VW/VD）与 dtype 宽度不一致时返回错误文案；一致返回 ''。

    规则（2026-11-12 用户确认：写了字节就严格按字节寻址）：
      VB1006 + bool         → 1 == 1  ✔
      VW1004 + uint16       → 2 == 2  ✔
      VD1000 + float32      → 4 == 4  ✔
      VB1006 + uint16       → 1 != 2  ✘ 报错（原来会被悄悄按 2 字节读，踩到 1007 的数据）
      V300   + float32      → 没写后缀，按 dtype，不拦
      V300.0 + bool         → 位地址，必须是 bool
    """
    if (protocol or "").lower() != "s7":
        return ""
    try:
        _area, _db, _off, _size, bit = parse_addr("s7", addr)
    except Exception:
        return ""
    if bit is not None:
        if (dtype or "").lower() != "bool":
            return f"{addr} 是位地址，数据类型必须是 bool（当前是 {dtype}）"
        return ""
    if (dtype or "").lower() == "string":
        return ""          # 字符串变长，另有 warning，不做宽度硬校验
    ek = s7_explicit_kind(addr)
    if not ek:
        return ""
    need = S7_KIND_SIZE[ek]
    got = type_size(dtype)
    if got != need:
        label = {"B": "字节", "W": "字", "D": "双字"}.get(ek, ek)
        return (f"{addr} 是{label}寻址（{need} 字节），但类型 {dtype} 占 {got} 字节。"
                f"字节地址用 bool，字地址用 int16/uint16，双字地址用 int32/uint32/float32；"
                f"或者把地址后缀改成匹配的。")
    return ""


def mc_is_word(area: str) -> bool:
    """MC 软元件是否按字读（块规划与读写都用它判断）"""
    return area in MC_WORD_DEVS


def addr_span(protocol: str, addr: str, dtype: str):
    """地址占用的 [起始单元, 结束单元)（用于重叠校验与显示）。
    返回 (area, start, end)：
      s7     **位偏移区间**（off*8 + bit）。位地址和字节/字/双字统一换算成位，
             这样 V300.0 与 V300.1 不重叠，但 V300.0 与 VW300 会重叠（它们确实重叠）。
             早期版本用字节偏移且忽略 bit，导致两个不同的位被判成同一区间。
      mc     字软元件：字编号区间 ×2 换算字节；位软元件：位编号（同区不重叠才放行）
      modbus 寄存器/线圈号区间
    bit_offset（从整数取位）对非位地址不改变占用区间。"""
    area, db, off, size, bit = parse_addr(protocol, addr)
    p = (protocol or "").lower()
    if p == "s7":
        key = f"{area}{db}" if area == "DB" else area
        if bit is not None:
            # 纯位地址（V300.0 / DB1.DBX300.0）：占 1 个位
            b0 = off * 8 + bit
            return key, b0, b0 + 1
        # 宽度规则（2026-11-12 定）：
        #   写了后缀（VB/VW/VD）→ **严格按后缀**，1/2/4 字节，dtype 必须匹配（validate 会拦）
        #   没写后缀（V300）  → 按 dtype 宽度（保留 V300 直接写 float32 这种习惯写法）
        # 之前一律按 dtype 算，导致 VB1006 + uint16 被当成 2 字节，
        # 和 V1007.1 报重叠 —— 校验没错，但根子在"地址语义被 dtype 覆盖了"。
        _ek = s7_explicit_kind(addr)
        n = _S7_KIND_SIZE[_ek] if _ek else max(type_size(dtype), 1)
        b0 = off * 8
        return key, b0, b0 + n * 8
    if p in ("mc", "mc_1e", "mc_3e"):
        if mc_is_word(area):
            n = max(1, type_size(dtype) // 2)
            return area, off * 2, (off + n) * 2      # 换算成字节便于重叠判断
        return area, off, off + 1                     # 位：编号即区间
    if p in ("modbus_tcp", "modbus_rtu"):
        n = max(1, type_size(dtype) // 2)
        return area, off, off + n
    area2, _db, off2, _s, _b = parse_addr(protocol, addr)
    return area2, off2, off2 + max(type_size(dtype) // 2, 1)


def check_alignment(protocol: str, addr: str, dtype: str):
    """类型与地址对齐（提示词校验 #4）。返回 (是否对齐, 中文原因)。
    s7  32 位类型字节偏移须 %4==0、16 位 %2==0
    mc  32 位类型字编号须为偶数（D100 可以、D101 不行）
    modbus 32 位类型寄存器偏移须为偶数"""
    p = (protocol or "").lower()
    area, db, off, size, bit = parse_addr(protocol, addr)
    need = type_size(dtype)
    if p == "s7":
        # S7-200 SMART 的 V 区是字节寻址：VD5517 表示 VB5517~VB5520 这 4 个字节，
        # VD5518 表示 VB5518~VB5521，两者都合法，不要求起始偏移是 4 的倍数。
        # 原来这里套用了 S7-300/400 DB 块（DB1.DBDn 必须 n%4==0）的对齐规则，
        # 对 V 区是误报（用户 2026-11 明确：VD5517 占 VB5517\VB5518\VB5519\VB5520）。
        # 越界由 addr_span + 区块边界检查负责；重叠由 validate_point 的区间相交负责。
        return True, ""
    if p in ("mc", "mc_1e", "mc_3e"):
        if mc_is_word(area) and need >= 4 and off % 2:
            return False, f"{addr} 不能放 32/64 位类型（三菱 32 位量要占偶数起始的 2 个字，D 编号须为偶数）"
        return True, ""
    if p in ("modbus_tcp", "modbus_rtu"):
        if need >= 4 and off % 2:
            return False, f"{addr} 不能放 32/64 位类型（Modbus 32 位量要占 2 个寄存器，偏移须为偶数）"
        return True, ""
    return True, ""


def readonly_area(protocol: str, addr: str) -> bool:
    """该地址是否落在只读区（rw=1 时用于校验 #6）"""
    try:
        area, _db, _off, _sz, _bit = parse_addr(protocol, addr)
    except ValueError:
        return False
    return area in READONLY_AREAS.get((protocol or "").lower(), set())
