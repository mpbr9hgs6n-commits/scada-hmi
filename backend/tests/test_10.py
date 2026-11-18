# -*- coding: utf-8 -*-
"""提示词 10 第 3 节 · 历史查询单元测试

覆盖：
  - 五维度 → 时间区间 + 粒度（年/月按天、日按分钟、时按秒）
  - 跨年/跨月边界（12 月 +1 → 次年 1 月；1 月 -1 不越界）
  - 超 2000 条自动降 5 秒（downgrade_gran）
  - 历史子表名规则 d_{site}_{point}
  - 删除历史的参数守卫（keep_days < 7 必须拒）

跑法（backend 容器内）：
  docker exec plant-backend python /app/tests/test_10.py
纯标准库断言，不依赖 pytest——镜像里没有的库不引。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.environ.get("TEST_APP_ROOT", "/app"))

from fastapi import HTTPException  # noqa: E402

from app.api.history import (  # noqa: E402
    _range_by_dims, downgrade_gran, MAX_POINTS, MAX_SERIES,
)
from app.service.point_service import hist_table_name  # noqa: E402
from app.core.validate import require_int  # noqa: E402

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


print("== 五维度 → 区间 + 粒度 ==")

f, t, g = _range_by_dims(2026, None, None, None)
check("只给年：整年、按天", (f, t, g) == (dt.datetime(2026, 1, 1), dt.datetime(2027, 1, 1), "1d"),
      "%s %s %s" % (f, t, g))

f, t, g = _range_by_dims(2026, 11, None, None)
check("年+月：整月、按天", (f, t, g) == (dt.datetime(2026, 11, 1), dt.datetime(2026, 12, 1), "1d"),
      "%s %s %s" % (f, t, g))

f, t, g = _range_by_dims(2026, 12, None, None)
check("12 月跨年：止点落到次年 1 月 1 日",
      (f, t, g) == (dt.datetime(2026, 12, 1), dt.datetime(2027, 1, 1), "1d"),
      "%s %s %s" % (f, t, g))

f, t, g = _range_by_dims(2026, 1, None, None)
check("1 月不前移：止点 2 月 1 日",
      (f, t, g) == (dt.datetime(2026, 1, 1), dt.datetime(2026, 2, 1), "1d"),
      "%s %s %s" % (f, t, g))

f, t, g = _range_by_dims(2026, 11, 9, None)
check("年+月+日：整天、按分钟",
      (f, t, g) == (dt.datetime(2026, 11, 9), dt.datetime(2026, 11, 10), "1m"),
      "%s %s %s" % (f, t, g))

f, t, g = _range_by_dims(2026, 11, 9, 14)
check("年+月+日+时：整小时、按秒",
      (f, t, g) == (dt.datetime(2026, 11, 9, 14), dt.datetime(2026, 11, 9, 15), "1s"),
      "%s %s %s" % (f, t, g))

f, t, g = _range_by_dims(2026, 11, 9, 23)
check("23 时跨日：止点次日 0 点",
      (f, t, g) == (dt.datetime(2026, 11, 9, 23), dt.datetime(2026, 11, 10, 0), "1s"),
      "%s %s %s" % (f, t, g))

try:
    _range_by_dims(2026, 2, 30, None)
    feb30 = False
except ValueError:
    feb30 = True
check("2 月 30 日不存在 → ValueError（接口翻成 400，不是 500）", feb30)

print("== 超 2000 条自动降 5 秒 ==")

check("MAX_POINTS=2000", MAX_POINTS == 2000, MAX_POINTS)
check("MAX_SERIES=20", MAX_SERIES == 20, MAX_SERIES)

check("按秒 2000 条：不降级",
      downgrade_gran("1s", 2000) == ("1s", ""), downgrade_gran("1s", 2000))
ng, note = downgrade_gran("1s", 2001)
check("按秒 2001 条：降 5 秒并给提示", ng == "5s" and "5 秒" in note, "%s %r" % (ng, note))
check("按天/按分不受影响",
      downgrade_gran("1m", 5000) == ("1m", "") and downgrade_gran("1d", 5000) == ("1d", ""),
      downgrade_gran("1d", 5000))

print("== 历史子表名 ==")

check("d_{site}_{point} 全小写", hist_table_name("S001", "LEVEL") == "d_s001_level",
      hist_table_name("S001", "LEVEL"))
check("非法字符被剔除", hist_table_name("S001", "A-B.C") == "d_s001_abc",
      hist_table_name("S001", "A-B.C"))

print("== 删除历史的参数守卫 ==")


def bad_of(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except HTTPException as e:
        return e.status_code
    return 0


check("keep_days=6 被拒（下限 7）", bad_of(require_int, "6", 7, 3650, "keep_days") == 400,
      bad_of(require_int, "6", 7, 3650, "keep_days"))
check("keep_days=7 通过", require_int("7", 7, 3650, "keep_days") == 7)
check("keep_days 非数字被拒", bad_of(require_int, "abc", 7, 3650, "keep_days") == 400)
check("keep_days 超上限被拒", bad_of(require_int, "99999", 7, 3650, "keep_days") == 400)

print("=" * 46)
print("PASS=%d  FAIL=%d" % (P, F))
sys.exit(0 if F == 0 else 1)
