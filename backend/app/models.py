from sqlalchemy import Column, BigInteger, Integer, SmallInteger, String, Text, DateTime, Double, Enum
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from .db import Base
from datetime import datetime

class Gateway(Base):
    """采集网关：一个网关一套独立 TDengine，共享 MySQL / Redis。

    为什么要独立 TDengine：历史数据量随时间线性增长，按网关分实例可以把
    容量、备份、清理都按网关边界切开，一个网关的库出问题不波及其他。
    mysql / redis 仍然共享 —— 站点、点位、画面、报警这些配置必须全局唯一，
    组态画面还要能混排多站点，分库会把全局视图打碎。
    """
    __tablename__ = "gateway"
    id = Column(String(32), primary_key=True)          # 对应容器环境变量 GATEWAY_ID
    name = Column(String(64), nullable=False)
    tdengine_url = Column(String(128), nullable=False)  # 该网关专属 TDengine REST
    remark = Column(String(255))
    created_at = Column(DateTime)


class Site(Base):
    """站点 = 一台 PLC（提示词 09：砍掉设备层，PLC 参数直接挂在站点上）

    plc_protocol / plc_ip / plc_port / rack / slot / slave_id 等通信参数
    由 2026-11-09-site.py 迁移从 device 表搬来；运行时字段（status/last_err/
    succ_rate）由网关回写，不是人工维护。
    """
    __tablename__ = "site"
    id = Column(String(16), primary_key=True)
    name = Column(String(64), nullable=False)
    # 所属网关（必填，一个网关最多 20 台 PLC）。网关按它决定采哪些站点。
    gateway_id = Column(String(32))
    group_id = Column(Integer)
    address = Column(String(128))
    lng = Column(Double)
    lat = Column(Double)
    # ---- PLC（一台，就是本站唯一的采集对象） ----
    plc_ip = Column(String(32), nullable=False)
    plc_protocol = Column(String(16), nullable=False)   # s7/mc/modbus_tcp/fins/ab_eth
    plc_port = Column(Integer, nullable=False)
    brand = Column(String(32))
    series = Column(String(32))
    comm_mode = Column(String(16), default="tcp")
    serial_params = Column(MySQLJSON)
    proto_params = Column(MySQLJSON)
    rack = Column(SmallInteger, default=0)
    slot = Column(SmallInteger, default=1)
    slave_id = Column(SmallInteger, default=1)
    timeout_ms = Column(Integer, default=3000)
    reconnect_ms = Column(Integer, default=3000)
    default_poll_ms = Column(Integer, default=1000)
    merge_addr = Column(SmallInteger, default=1)
    max_batch = Column(Integer, default=120)
    retry = Column(Integer, default=2)
    offline_threshold = Column(Integer, default=3)
    # ---- 心跳判定（提示词 10：modbus_echo / ping 二选一） ----
    heartbeat_mode = Column(String(16), default="none")
    hb_write_addr = Column(Integer, default=0)     # Modbus 0-based：40001 -> 0
    hb_read_addr = Column(Integer, default=1)      # 40002 -> 1
    hb_max_value = Column(Integer, default=2000)   # 写入值循环上限 1~2000
    hb_cycles = Column(SmallInteger, default=3)    # 连续失败判定周期数
    # 双端口回环：写走一条 TCP、读走另一条（如 506 写 / 507 读）。
    # NULL = 用站点 plc_port（同端口回环，省一条连接）。
    hb_write_port = Column(Integer)
    hb_read_port = Column(Integer)
    # 回环节奏：0 = 每轮采集都跑；>0 = 独立按 N 秒跑一次（循环值只在到点时推进）
    hb_interval_s = Column(Integer, default=0)
    ping_interval_ms = Column(Integer, default=5000)
    location = Column(String(64))
    # ---- 运行时（网关回写） ----
    enabled = Column(SmallInteger, default=1)
    status = Column(SmallInteger, default=0)
    last_err = Column(String(128))
    succ_rate = Column(Double)
    remark = Column(String(255))
    created_at = Column(DateTime, default=datetime.now)


class Point(Base):
    """采集点位：只挂站点（site_id），不挂设备 —— 09 迁移删掉了 device_id"""
    __tablename__ = "point"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    site_id = Column(String(16), nullable=False)       # 唯一键 (site_id, code)
    code = Column(String(32), nullable=False)
    name = Column(String(64))
    descr = Column(String(128))
    group_name = Column(String(32))                # 工艺段
    sort_no = Column(Integer, default=0)
    save_history = Column(SmallInteger, default=0) # 20万点位不可能全存
    hist_interval = Column(Integer, default=60)    # 历史间隔（秒），0=全局默认
    offset_val = Column(Double, default=0)         # y = k*x + b 的 b
    valuelist_id = Column(Integer)                 # 枚举列表 → valuelist.id
    alarm_hh = Column(Double)
    alarm_h = Column(Double)
    alarm_l = Column(Double)
    alarm_ll = Column(Double)
    alarm_hyst = Column(Double, default=0)
    alarm_delay = Column(Integer, default=0)       # 报警延时（秒）
    alarm_level = Column(String(16))               # 一般/重要/紧急
    is_kpi = Column(SmallInteger, default=0)
    write_confirm = Column(SmallInteger, default=0)
    addr = Column(String(48), nullable=False)
    dtype = Column(String(16), nullable=False)
    byte_order = Column(String(8), default="ABCD")
    bit_offset = Column(SmallInteger)
    poll_ms = Column(Integer)
    unit = Column(String(16))
    scale_min = Column(Double)
    scale_max = Column(Double)
    decimals = Column(SmallInteger, default=2)
    rw = Column(SmallInteger, default=0)
    # 导入时校验出的问题（用户 2026-11：不再阻断导入，问题只记录不拦）
    import_error = Column(String(255))
    deadband = Column(Double, default=0.5)
    enabled = Column(SmallInteger, default=1)

class Page(Base):
    __tablename__ = "page"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    template_id = Column(Integer)
    site_id = Column(String(16))
    name = Column(String(64), nullable=False)
    kind = Column(Enum("template", "scada", "screen", "video_wall"), default="scada")
    # 14 号：发布状态（1=已发布，出现在 /publish 的目录树里）
    published = Column(SmallInteger, nullable=False, default=0)
    pub_sort = Column(Integer, nullable=False, default=0)
    json = Column(Text)
    locked = Column(SmallInteger, default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class Faceplate(Base):
    """组件模板类型（P8）—— 官方 4.6：类型 + 实例模型

    json           类型内部对象定义（相对坐标，与画面同构）
    iface          接口变量定义 [{"name":"PV","type":"real","default":0,"desc":"液位"}]
    实例只存 fpt_id + bindings，渲染时实时读本表 —— 拷贝 json 的话「改模板同步变」就失效了
    """
    __tablename__ = "faceplate"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    w = Column(Integer, default=200)
    h = Column(Integer, default=200)
    json = Column(Text)
    iface = Column(Text)
    locked = Column(SmallInteger, default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ValueList(Base):
    """文本列表 / 图形列表（P8，官方 4.7）

    kind = text：items=[{"value":0,"text":"停止"}]
    kind = graph：items=[{"value":0,"image":"/api/upload/xxx.png"}]
    """
    __tablename__ = "valuelist"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    kind = Column(String(8), default="text")
    items = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PointMap(Base):
    __tablename__ = "point_map"
    template_id = Column(Integer, primary_key=True)
    site_id = Column(String(16), primary_key=True)
    logical = Column("logical", String(32), primary_key=True)
    point_code = Column(String(32), nullable=False)

class Alarm(Base):
    __tablename__ = "alarm"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    site_id = Column(String(16), nullable=False)
    point_code = Column(String(32), nullable=False)
    level = Column(SmallInteger, default=2)
    state = Column(SmallInteger, default=0)
    val = Column(Double)
    threshold = Column(Double)
    msg = Column(String(255))
    first_ts = Column(DateTime, nullable=False)
    last_ts = Column(DateTime, nullable=False)
    count = Column(Integer, default=1)
    shielded = Column(SmallInteger, default=0)
    ack_user = Column(String(32))
    ack_ts = Column(DateTime)
    ack_note = Column(String(255))

class AlarmEvent(Base):
    __tablename__ = "alarm_event"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    alarm_id = Column(BigInteger)
    site_id = Column(String(16))
    point_code = Column(String(32))
    action = Column(String(16))
    val = Column(Double)
    user_name = Column(String(32))
    note = Column(String(255))
    ts = Column(DateTime, default=datetime.now)

class User(Base):
    __tablename__ = "sys_user"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(32), nullable=False, unique=True)
    pwd_hash = Column(String(72), nullable=False)
    real_name = Column(String(32))
    role_code = Column(String(16), nullable=False, default="viewer")
    phone = Column(String(20))
    status = Column(SmallInteger, default=1)
    pwd_updated_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

class Role(Base):
    __tablename__ = "sys_role"
    code = Column(String(16), primary_key=True)
    name = Column(String(32), nullable=False)
    perms = Column(Text)

class UserSite(Base):
    __tablename__ = "sys_user_site"
    user_id = Column(BigInteger, primary_key=True)
    site_id = Column(String(16), primary_key=True)

class LoginLog(Base):
    __tablename__ = "sys_login_log"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(32))
    ip = Column(String(64))
    ua = Column(String(255))
    ok = Column(SmallInteger)
    reason = Column(String(128))
    ts = Column(DateTime, default=datetime.now)

class OpLog(Base):
    __tablename__ = "sys_op_log"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(32))
    site_id = Column(String(16))
    point_code = Column(String(32))
    action = Column(String(32))
    old_val = Column(String(64))
    new_val = Column(String(64))
    ip = Column(String(64))
    # P5：写入结果 ok / fail:mismatch / fail:timeout / fail:gw / fail:gw_down
    result = Column(String(16))
    ts = Column(DateTime, default=datetime.now)


class Camera(Base):
    """监控摄像机（01 迁移新建，04 配界面）

    password_enc 只存 AES 密文，任何接口不得返回明文（返回统一 "******"）。
    sort_no 决定 /api/video/cameras 的返回顺序——组态视频控件按列表下标取通道，
    乱改会把已存画面的视频串台。
    """
    __tablename__ = "camera"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    site_id = Column(String(16), nullable=False)
    code = Column(String(32), nullable=False, unique=True)   # S001-CAM01
    name = Column(String(64), nullable=False)                # 每路监控的名称：进水口
    location = Column(String(64))
    brand = Column(String(32))       # dahua/hikvision/uniview/tiandy/tplink/huawei/other
    model = Column(String(64))
    serial_no = Column(String(64))
    ip = Column(String(64))
    http_port = Column(Integer, default=80)
    rtsp_port = Column(Integer, default=554)
    sdk_port = Column(Integer, default=0)
    username = Column(String(64))
    password_enc = Column(String(255))                       # AES 密文
    access_type = Column(String(16), default="rtsp")         # 目前只支持 rtsp
    channel_no = Column(Integer, default=1)                  # 海康NVR: URL 里是 {n}01
    rtsp_main = Column(String(512))
    rtsp_sub = Column(String(512))
    codec = Column(String(16))       # 主码流编码 H264/H265/MJPEG
    codec_sub = Column(String(16))   # 子码流编码（2026-11-13 加：主辅码流可分开探测）
    resolution = Column(String(16))
    fps = Column(Integer)
    bitrate = Column(Integer)
    ptz = Column(SmallInteger, default=0)
    ptz_protocol = Column(String(32))
    preset_count = Column(Integer, default=0)
    has_audio = Column(SmallInteger, default=0)
    has_alarm_in = Column(SmallInteger, default=0)
    record_enable = Column(SmallInteger, default=1)
    record_plan = Column(String(64), default="7x24")
    keep_days = Column(Integer, default=30)
    wall_slot = Column(Integer, default=0)                   # 监控墙分屏位，0=未分配
    sort_no = Column(Integer, default=0)
    lng = Column(Double)
    lat = Column(Double)
    status = Column(SmallInteger, default=0)                 # 0离线 1在线
    last_online_at = Column(DateTime)
    remark = Column(String(255))
    enabled = Column(SmallInteger, default=1)
    created_at = Column(DateTime, default=datetime.now)


class SysConfig(Base):
    """平台级参数（键值对）。gb28181.* / sample.* / history.* / backup.*"""
    __tablename__ = "sys_config"
    key = Column("key", String(64), primary_key=True)
    value = Column(Text)
    descr = Column(String(255))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class CustomObject(Base):
    """对象库自定义图元。

    每组（标准对象 std / 智能对象 smart / 工艺图元 craft / 大屏组件 screen / 控件符号 ctrl）
    都可以挂用户自己做的图。图片本身走 /api/upload 存文件，这里只记地址和展示尺寸。
    拖到画布时生成一个 image 类型对象（type=image, src=<image_url>）。
    """
    __tablename__ = "custom_object"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    group_key = Column(String(16), nullable=False, default="craft")
    name = Column(String(64), nullable=False)
    image_url = Column(String(255), nullable=False)
    w = Column(Integer, default=120)
    h = Column(Integer, default=60)
    sort = Column(Integer, default=0)
    enabled = Column(SmallInteger, default=1)
    created_by = Column(String(32))
    created_at = Column(DateTime, default=datetime.now)
