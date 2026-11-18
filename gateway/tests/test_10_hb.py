# -*- coding: utf-8 -*-
"""提示词 10 第 2 节 · 心跳状态机单元测试

覆盖：
  - 状态迁移：unknown → online → suspect → offline → online（恢复）
  - 单次失败只到 suspect，不直接把在线打成离线（防抖）
  - cycles 边界：0/负数按 1 处理；连续 N 次才判离线
  - feed() 只在状态**变化**时返回状态，没变化返回 None（网关据此才写库/写 Redis）

跑法（网关容器内）：
  docker exec plant-gateway python /app/tests/test_10_hb.py
纯标准库断言，不依赖 pytest——镜像里没有的库不引。
"""
import os
import sys

sys.path.insert(0, os.environ.get("HB_ROOT", "/app"))

from heartbeat import StatusMachine, ONLINE, SUSPECT, OFFLINE, UNKNOWN  # noqa: E402

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


print("== 状态机基础迁移 ==")

m = StatusMachine(3)
check("初始态是 unknown", m.state == UNKNOWN, m.state)

r = m.feed(True)
check("unknown --成功--> online", r == ONLINE and m.state == ONLINE, "r=%r state=%s" % (r, m.state))

r = m.feed(True)
check("已在 online 再成功：状态不变、feed 返回 None（不重复写库）", r is None, "r=%r" % (r,))

r = m.feed(False)
check("online --1 次失败--> suspect（不直接判离线）", r == SUSPECT and m.state == SUSPECT,
      "r=%r state=%s" % (r, m.state))

r = m.feed(False)
check("suspect 第 2 次失败仍是 suspect，返回 None", r is None and m.state == SUSPECT,
      "r=%r state=%s" % (r, m.state))

r = m.feed(False)
check("连续 3 次失败（cycles=3）--> offline", r == OFFLINE and m.state == OFFLINE,
      "r=%r state=%s" % (r, m.state))

r = m.feed(False)
check("offline 继续失败：仍是 offline，返回 None", r is None and m.state == OFFLINE,
      "r=%r state=%s" % (r, m.state))

r = m.feed(True)
check("offline --一次成功--> online（立即恢复）", r == ONLINE and m.state == ONLINE,
      "r=%r state=%s" % (r, m.state))

print("== cycles 边界 ==")

m = StatusMachine(1)
m.feed(True)
r = m.feed(False)
check("cycles=1：一次失败直接离线", r == OFFLINE and m.state == OFFLINE,
      "r=%r state=%s" % (r, m.state))

m = StatusMachine(0)
check("cycles=0 被夹到 1", m.cycles == 1, m.cycles)
m = StatusMachine(-5)
check("cycles=-5 被夹到 1", m.cycles == 1, m.cycles)
m = StatusMachine(None)
check("cycles=None 退化为 3", m.cycles == 3, m.cycles)

print("== 失败计数在恢复后清零 ==")

m = StatusMachine(3)
m.feed(True)
m.feed(False)          # suspect, fails=1
m.feed(False)          # fails=2
m.feed(True)           # 恢复
check("恢复后 fails 清零", m.fails == 0, m.fails)
r = m.feed(False)
check("恢复后再失败重新从 suspect 起步（不能沿用旧计数）",
      r == SUSPECT and m.state == SUSPECT, "r=%r state=%s" % (r, m.state))

print("== 从 unknown 直接失败（PLC 一开始就连不上）==")

m = StatusMachine(2)
r = m.feed(False)
check("unknown --1 次失败--> 仍是 unknown（从没在线过，不冒充 suspect），也不写库",
      r is None and m.state == UNKNOWN, "r=%r state=%s" % (r, m.state))
r = m.feed(False)
check("连续 2 次失败 --> offline", r == OFFLINE and m.state == OFFLINE,
      "r=%r state=%s" % (r, m.state))
r = m.feed(False)
check("offline 继续失败不重复写库", r is None and m.state == OFFLINE,
      "r=%r state=%s" % (r, m.state))

print("== S7 读多少字节：地址写法与数据类型取大 ==")
# 现场坑：S001 加了 VB1006（写法 1 字节）但 dtype=uint16，只读 1 字节再按 uint16 解
# 会抛 "unpack requires a buffer of 2 bytes"，整个站点被判离线。
try:
    from collector import s7_span

    a = s7_span({"addr": "VB1006", "dtype": "uint16"})
    check("VB1006 + uint16 → 读 2 字节", a[3] == 2, a)
    a = s7_span({"addr": "VD1000", "dtype": "float32"})
    check("VD1000 + float32 → 读 4 字节", a[3] == 4, a)
    a = s7_span({"addr": "VW100", "dtype": "uint16"})
    check("VW100 + uint16 → 读 2 字节", a[3] == 2, a)
    a = s7_span({"addr": "V1007.1", "dtype": "bool"})
    check("V1007.1 位地址 → 读 1 字节、位号 1", a[3] == 1 and a[4] == 1, a)
    a = s7_span({"addr": "VB0", "dtype": "uint8"})
    check("未知类型按 2 字节兜底（与 type_size 一致）", a[3] == 2, a)
except Exception as e:      # noqa: BLE001
    check("导入 collector.s7_span", False, repr(e))

print("=" * 46)
print("PASS=%d  FAIL=%d" % (P, F))
sys.exit(0 if F == 0 else 1)
