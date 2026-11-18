"""报警状态机（网关侧调用，共享 MySQL）

每次状态变化后向 Redis 推一条报警事件（core/realtime.publish_alarm），
SSE 端点 /api/alarm/subscribe 消费 —— 报警窗靠它实时刷新，不靠轮询。
"""
from datetime import datetime
from sqlalchemy.orm import Session
from ..models import Alarm, AlarmEvent
from .realtime import publish_alarm


def _push(a: Alarm, act: str):
    """把报警当前状态推给订阅者（含首次产生/更新/恢复/确认/关闭）"""
    publish_alarm({
        "act": act, "id": a.id, "site": a.site_id, "point": a.point_code,
        "level": a.level, "state": a.state, "val": a.val, "threshold": a.threshold,
        "msg": a.msg, "first_ts": str(a.first_ts or ""), "last_ts": str(a.last_ts or ""),
        "count": a.count, "ack_user": a.ack_user or "",
    })

def _active_alarm(db: Session, site_id, code):
    return db.query(Alarm).filter(Alarm.site_id == site_id,
                                  Alarm.point_code == code,
                                  Alarm.state.in_([0, 1])).first()

def on_value(db: Session, site_id: str, code: str, name: str, val: float,
             scale_min, scale_max):
    """报警判定：越上/下限产生报警，回到区间恢复。返回动作名。"""
    now = datetime.now()
    exceeded = None
    if scale_max is not None and val > scale_max:
        exceeded = ("上限", scale_max, 2)
    elif scale_min is not None and val < scale_min:
        exceeded = ("下限", scale_min, 2)
    a = _active_alarm(db, site_id, code)
    if exceeded:
        if a is None:
            a = Alarm(site_id=site_id, point_code=code, level=exceeded[2], state=0,
                      val=val, threshold=exceeded[1],
                      msg=f"{name or code} 超出{exceeded[0]} {exceeded[1]}",
                      first_ts=now, last_ts=now, count=1)
            db.add(a); db.flush()
            db.add(AlarmEvent(alarm_id=a.id, site_id=site_id, point_code=code,
                              action="raise", val=val, ts=now))
            db.commit()
            _push(a, "raise")
            return "raise"
        else:
            a.val = val; a.last_ts = now; a.count = (a.count or 1) + 1
            if a.state == 2:  # 抖动恢复后再次越限
                a.state = 0
                db.add(AlarmEvent(alarm_id=a.id, site_id=site_id, point_code=code,
                                  action="raise", val=val, ts=now))
            db.commit()
            _push(a, "update")
            return "update"
    else:
        if a is not None and a.state in (0, 1):
            a.state = 2; a.last_ts = now; a.val = val
            db.add(AlarmEvent(alarm_id=a.id, site_id=site_id, point_code=code,
                              action="recover", val=val, ts=now))
            db.commit()
            _push(a, "recover")
            return "recover"
    return "none"

def ack(db: Session, alarm_id: int, user: str, note: str = ""):
    a = db.query(Alarm).filter(Alarm.id == alarm_id).first()
    if not a:
        return None
    a.state = 1; a.ack_user = user; a.ack_ts = datetime.now(); a.ack_note = note
    db.add(AlarmEvent(alarm_id=a.id, site_id=a.site_id, point_code=a.point_code,
                      action="ack", user_name=user, note=note, val=a.val))
    db.commit()
    _push(a, "ack")
    return a

def close(db: Session, alarm_id: int, user: str):
    a = db.query(Alarm).filter(Alarm.id == alarm_id).first()
    if not a:
        return None
    a.state = 3; a.ack_user = user; a.ack_ts = datetime.now()
    db.add(AlarmEvent(alarm_id=a.id, site_id=a.site_id, point_code=a.point_code,
                      action="close", user_name=user, val=a.val))
    db.commit()
    _push(a, "close")
    return a
