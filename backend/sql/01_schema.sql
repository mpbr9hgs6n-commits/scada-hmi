SET NAMES utf8mb4;

-- ========== 站点 ==========
CREATE TABLE IF NOT EXISTS site (
  id          VARCHAR(16)  PRIMARY KEY COMMENT '站点编号 S001',
  name        VARCHAR(64)  NOT NULL COMMENT '站点名称',
  group_id    INT          DEFAULT NULL COMMENT '分组（区域/车间）',
  address     VARCHAR(128) DEFAULT NULL,
  lng         DECIMAL(10,7) DEFAULT NULL,
  lat         DECIMAL(10,7) DEFAULT NULL,
  plc_ip      VARCHAR(32)  DEFAULT NULL,
  protocol    VARCHAR(16)  DEFAULT NULL COMMENT 's7/mc/fins/modbus_tcp/modbus_rtu/opcua/cip',
  plc_port    INT          DEFAULT NULL,
  status      TINYINT      DEFAULT 0 COMMENT '0未知 1在线 2离线',
  remark      VARCHAR(255) DEFAULT NULL,
  created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='站点';

-- ========== 设备（每站一台 PLC） ==========
CREATE TABLE IF NOT EXISTS device (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  site_id     VARCHAR(16) NOT NULL,
  name        VARCHAR(64),
  model       VARCHAR(32) COMMENT 'S7-200SMART/FX3U/H5U/CP1E/AB',
  protocol    VARCHAR(16) NOT NULL,
  ip          VARCHAR(32) NOT NULL,
  port        INT         NOT NULL,
  rack        SMALLINT    DEFAULT 0,
  slot        SMALLINT    DEFAULT 1,
  slave_id    SMALLINT    DEFAULT 1,
  timeout_ms  INT         DEFAULT 3000,
  reconnect_ms INT        DEFAULT 3000,
  default_poll_ms INT     DEFAULT 1000,
  enabled     TINYINT     DEFAULT 1,
  UNIQUE KEY uk_site (site_id),
  KEY idx_ip (ip)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PLC设备';

-- ========== 点位（唯一事实来源，采集与组态共用） ==========
CREATE TABLE IF NOT EXISTS point (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  device_id   BIGINT      NOT NULL,
  site_id     VARCHAR(16) NOT NULL,
  code        VARCHAR(32) NOT NULL COMMENT '点位编码 LEVEL / PUMP1_RUN',
  name        VARCHAR(64) COMMENT '中文名',
  addr        VARCHAR(48) NOT NULL COMMENT 'VD1000 / D100 / W0.00',
  dtype       VARCHAR(16) NOT NULL COMMENT 'bool/int16/uint16/int32/uint32/float32/float64/string',
  byte_order  VARCHAR(8)  DEFAULT 'ABCD' COMMENT 'ABCD/CDAB/BADC/DCBA',
  bit_offset  TINYINT     DEFAULT NULL,
  poll_ms     INT         DEFAULT NULL COMMENT 'NULL=继承设备默认',
  unit        VARCHAR(16),
  scale_min   DOUBLE,
  scale_max   DOUBLE,
  decimals    TINYINT     DEFAULT 2,
  rw          TINYINT     DEFAULT 0 COMMENT '0只读 1读写',
  deadband    DOUBLE      DEFAULT 0.5 COMMENT '百分比',
  enabled     TINYINT     DEFAULT 1,
  UNIQUE KEY uk_site_code (site_id, code),
  KEY idx_device (device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='点位定义';

-- ========== 画面（模板/实例/大屏 一张表） ==========
CREATE TABLE IF NOT EXISTS page (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  template_id INT          DEFAULT NULL COMMENT '实例来源模板',
  site_id     VARCHAR(16)  DEFAULT NULL,
  name        VARCHAR(64)  NOT NULL,
  kind        ENUM('template','scada','screen') DEFAULT 'scada',
  json        JSON,
  locked      TINYINT      DEFAULT 0 COMMENT '1=重刷模板时跳过',
  updated_at  DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tpl_site (template_id, site_id),
  KEY idx_kind (kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='组态画面';

-- ========== 逻辑名映射（只存例外，同名不落表） ==========
CREATE TABLE IF NOT EXISTS point_map (
  template_id INT         NOT NULL,
  site_id     VARCHAR(16) NOT NULL,
  `logical`   VARCHAR(32) NOT NULL COMMENT '模板里的逻辑名 LEVEL',
  point_code  VARCHAR(32) NOT NULL COMMENT '该站实际点位编码',
  PRIMARY KEY (template_id, site_id, `logical`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='逻辑名映射';

-- ========== 报警 ==========
CREATE TABLE IF NOT EXISTS alarm (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  site_id     VARCHAR(16) NOT NULL,
  point_code  VARCHAR(32) NOT NULL,
  level       TINYINT     DEFAULT 2 COMMENT '1紧急 2重要 3一般',
  state       TINYINT     DEFAULT 0 COMMENT '0报警 1已确认 2已恢复 3已关闭',
  val         DOUBLE,
  threshold   DOUBLE,
  msg         VARCHAR(255),
  first_ts    DATETIME    NOT NULL,
  last_ts     DATETIME    NOT NULL,
  count       INT         DEFAULT 1 COMMENT '聚合次数',
  shielded    TINYINT     DEFAULT 0,
  ack_user    VARCHAR(32),
  ack_ts      DATETIME,
  ack_note    VARCHAR(255),
  KEY idx_site_state (site_id, state),
  KEY idx_ts (first_ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='当前报警';

CREATE TABLE IF NOT EXISTS alarm_event (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  alarm_id    BIGINT,
  site_id     VARCHAR(16),
  point_code  VARCHAR(32),
  action      VARCHAR(16) COMMENT 'raise/ack/recover/close/shield',
  val         DOUBLE,
  user_name   VARCHAR(32),
  note        VARCHAR(255),
  ts          DATETIME    DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ts (ts),
  KEY idx_site (site_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='报警流水';

-- ========== 用户与权限 ==========
CREATE TABLE IF NOT EXISTS sys_user (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  username    VARCHAR(32) NOT NULL UNIQUE,
  pwd_hash    VARCHAR(72) NOT NULL COMMENT 'bcrypt',
  real_name   VARCHAR(32),
  role_code   VARCHAR(16) NOT NULL DEFAULT 'viewer',
  phone       VARCHAR(20),
  status      TINYINT     DEFAULT 1,
  pwd_updated_at DATETIME,
  created_at  DATETIME    DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户';

CREATE TABLE IF NOT EXISTS sys_role (
  code  VARCHAR(16) PRIMARY KEY,
  name  VARCHAR(32) NOT NULL,
  perms JSON
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_user_site (
  user_id BIGINT      NOT NULL,
  site_id VARCHAR(16) NOT NULL,
  PRIMARY KEY (user_id, site_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='区域运维只管自己的站';

CREATE TABLE IF NOT EXISTS sys_login_log (
  id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(32), ip VARCHAR(64), ua VARCHAR(255),
  ok      TINYINT, reason VARCHAR(128),
  ts      DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sys_op_log (
  id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(32), site_id VARCHAR(16), point_code VARCHAR(32),
  action  VARCHAR(32), old_val VARCHAR(64), new_val VARCHAR(64),
  ip      VARCHAR(64), ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ts (ts), KEY idx_site (site_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='操作日志';

-- ========== 初始化数据 ==========
INSERT INTO sys_role(code,name) VALUES
 ('admin','系统管理员'),('operator','值班员'),('site_op','区域运维'),('viewer','只读')
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- 默认管理员不在 SQL 里插：bcrypt hash 运行时由后端生成。
-- 后端首次启动检测 sys_user 为空 -> 创建 admin / Admin@2026（bcrypt）
-- pwd_updated_at 置 NULL 表示未改过初始密码，登录后强制修改。
