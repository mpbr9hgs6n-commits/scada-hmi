# -*- coding: utf-8 -*-
"""09 站点与点位管理 · 单元测试（提示词 10 交付物 7）

覆盖：
  - 校验规则 12 条各一例（core/validate.py::validate_point）
  - 地址解析各协议各一例（core/addr.py::parse_addr，shared/addr.py 唯一实现）

跑法（backend 容器内）：
  docker exec plant-backend python /app/tests/test_09.py
纯标准库断言，不依赖 pytest——镜像里没有的库不引。
"""
import os
import sys

sys.path.insert(0, os.environ.get("TEST_APP_ROOT", "/app"))

from app.core.addr import parse_addr, type_size, valid_addr, mc_is_word  # noqa: E402
from app.core.validate import validate_point  # noqa: E402

P = 0
F = 0


def check(name, cond, detail=""):
    global P, F
    if cond:
        P += 1
        print("  [PASS] %s" % name)
    else:
        F += 1
        print("  [FAIL] %s  %s" % (name, detail))


def first_field(errors, field):
    return next((e for e in errors if e["field"] == field), None)


S7 = {"plc_protocol": "s7", "timeout_ms": 3000, "default_poll_ms": 1000}
MB = {"plc_protocol": "modbus_tcp", "timeout_ms": 3000, "default_poll_ms": 1000}


def pt(**kw):
    base = {"code": "T1", "name": "测试", "addr": "VD1000", "dtype": "float32"}
    base.update(kw)
    return base


print("== 校验规则 12 条（validate_point） ==")

# 1 编码站内唯一
e, w = validate_point(pt(code="LEVEL"), S7, [{"code": "LEVEL", "addr": "VD1004", "dtype": "float32"}])
check("1 编码重复被拒", first_field(e, "code") and "已存在" in first_field(e, "code")["msg"], str(e))

# 2 编码字符集
e, w = validate_point(pt(code="level-x"), S7, [])
check("2 非法字符被拒", first_field(e, "code") and "只能大写字母" in first_field(e, "code")["msg"], str(e))

# 3 地址符合协议写法
e, w = validate_point(pt(addr="VD1000"), MB, [])
check("3 协议地址格式被拒", first_field(e, "addr") and "不是 modbus_tcp 的合法地址" in first_field(e, "addr")["msg"], str(e))

# 4 类型与地址对齐
e, w = validate_point(pt(addr="VD1001"), S7, [])
check("4 32位未对齐被拒", first_field(e, "addr") and "未对齐" in first_field(e, "addr")["msg"], str(e))
e, w = validate_point(pt(addr="D101", dtype="float32"),
                      {"plc_protocol": "mc", "timeout_ms": 3000}, [])
check("4b MC 32位奇数字被拒", first_field(e, "addr") and "偶数" in first_field(e, "addr")["msg"], str(e))
e, w = validate_point(pt(addr="40002"), MB, [])
check("4c Modbus 32位奇偏移被拒", first_field(e, "addr") and "偏移须为偶数" in first_field(e, "addr")["msg"], str(e))

# 5 地址重叠
e, w = validate_point(pt(code="P2", addr="VD1000", dtype="int16"), S7,
                      [{"code": "LEVEL", "addr": "VD1000", "dtype": "float32"}])
check("5 地址重叠被拒", first_field(e, "addr") and "重叠" in first_field(e, "addr")["msg"], str(e))

# 6 可写区
e, w = validate_point(pt(addr="IW0", rw=1), S7, [])
check("6 只读区 rw 被拒", first_field(e, "addr") and "只读区" in first_field(e, "addr")["msg"], str(e))

# 7 poll_ms 范围
e, w = validate_point(pt(poll_ms=50), S7, [])
check("7 周期超范围被拒", first_field(e, "poll_ms") and "100~60000" in first_field(e, "poll_ms")["msg"], str(e))

# 8 周期不小于站点超时
e, w = validate_point(pt(poll_ms=1000), S7, [])
check("8 周期小于超时被拒", first_field(e, "poll_ms") and "小于站点超时" in first_field(e, "poll_ms")["msg"], str(e))

# 9 周期×点位数 警告不阻断（poll 缺省继承站点 1000ms：不触发规则 8，只给警告）
others = [{"code": "P%d" % i, "addr": "VD%d" % (2000 + i * 4), "dtype": "float32"}
          for i in range(500)]
e, w = validate_point(pt(poll_ms=None), S7, others)
check("9 大点数只警告", not e and any("超出 PLC 响应能力" in x for x in w), "errors=%s warnings=%s" % (e, w))

# 10 量程
e, w = validate_point(pt(scale_min=10, scale_max=1), S7, [])
check("10 量程下限大于上限被拒", first_field(e, "scale_max") and "下限必须小于上限" in first_field(e, "scale_max")["msg"], str(e))

# 11 小数位
e, w = validate_point(pt(decimals=5), S7, [])
check("11 小数位越界被拒", first_field(e, "decimals") and "0~4" in first_field(e, "decimals")["msg"], str(e))

# 12 位偏移仅整数
e, w = validate_point(pt(bit_offset=3), S7, [])
check("12 浮点带位偏移被拒", first_field(e, "bit_offset") and "位偏移" in first_field(e, "bit_offset")["msg"], str(e))

print("== 地址解析（parse_addr，各协议各一例） ==")

check("s7 VD1000", parse_addr("s7", "VD1000") == ("V", 1, 1000, 4, None),
      str(parse_addr("s7", "VD1000")))
check("s7 位 M10.1", parse_addr("s7", "M10.1") == ("M", 0, 10, 1, 1),
      str(parse_addr("s7", "M10.1")))
check("s7 DB1.DBD0", parse_addr("s7", "DB1.DBD0") == ("DB", 1, 0, 4, None),
      str(parse_addr("s7", "DB1.DBD0")))
check("mc D1018", parse_addr("mc", "D1018") == ("D", 0, 1018, 2, None),
      str(parse_addr("mc", "D1018")))
check("mc M100 位软元件", parse_addr("mc", "M100") == ("M", 0, 100, 1, None)
      and mc_is_word("D") and not mc_is_word("M"), "")
check("mc_1e 别名同 mc", parse_addr("mc_1e", "D1018") == parse_addr("mc", "D1018"), "")
check("modbus HR8", parse_addr("modbus_tcp", "HR8") == ("HR", 0, 8, 2, None),
      str(parse_addr("modbus_tcp", "HR8")))
check("modbus 40001", parse_addr("modbus_tcp", "40001") == ("HR", 0, 0, 2, None),
      str(parse_addr("modbus_tcp", "40001")))
check("modbus 线圈 0x00001", parse_addr("modbus_tcp", "0x00001") == ("C", 0, 0, 1, None),
      str(parse_addr("modbus_tcp", "0x00001")))
check("modbus 输入寄存器 30002", parse_addr("modbus_tcp", "30002") == ("IR", 0, 1, 2, None),
      str(parse_addr("modbus_tcp", "30002")))
check("fins D100", parse_addr("fins", "D100") == ("D", 0, 100, 2, None),
      str(parse_addr("fins", "D100")))
check("fins W0.00 位", parse_addr("fins", "W0.00") == ("W", 0, 0, 1, 0),
      str(parse_addr("fins", "W0.00")))
check("type_size 表", type_size("bool") == 1 and type_size("int16") == 2
      and type_size("float32") == 4 and type_size("float64") == 8, "")
ok_v, _ = valid_addr("s7", "VD1000")
bad_v, hint_v = valid_addr("s7", "WHAT")
check("valid_addr 红绿", ok_v and not bad_v and hint_v, "")

print("== 汇总 ==")
print("PASS=%d FAIL=%d" % (P, F))
raise SystemExit(0 if F == 0 else 1)
