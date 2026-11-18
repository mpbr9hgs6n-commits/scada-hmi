-- 种子数据：必须显式声明字符集，否则客户端按 latin1 解释 UTF-8 字节会造成双重编码乱码
SET NAMES utf8mb4;

-- 演示站点（Modbus 模拟器在 gateway 容器内 15020/15021/15022）
INSERT INTO site(id,name,group_id,address,protocol,plc_ip,plc_port,status,remark) VALUES
 ('S001','第一污水处理厂',1,'演示数据-厂区1','modbus_tcp','127.0.0.1',15020,1,'模拟站点'),
 ('S002','第二污水处理厂',1,'演示数据-厂区2','modbus_tcp','127.0.0.1',15021,1,'模拟站点'),
 ('S003','第三污水处理厂',2,'演示数据-厂区3','modbus_tcp','127.0.0.1',15022,1,'模拟站点')
ON DUPLICATE KEY UPDATE name=VALUES(name), protocol=VALUES(protocol);

INSERT INTO device(site_id,name,model,protocol,ip,port,slave_id,default_poll_ms) VALUES
 ('S001','S001-PLC','模拟PLC','modbus_tcp','127.0.0.1',15020,1,1000),
 ('S002','S002-PLC','模拟PLC','modbus_tcp','127.0.0.1',15021,1,1000),
 ('S003','S003-PLC','模拟PLC','modbus_tcp','127.0.0.1',15022,1,1000)
ON DUPLICATE KEY UPDATE ip=VALUES(ip), port=VALUES(port);

-- 点位：每站相同结构。0~9 号寄存器为浮点（前 50 个寄存器区模拟浮点液位）
-- float32 占 2 个寄存器：LEVEL=HR0, PH=HR2, FLOW=HR4, DO=HR6, TEMP=HR8
-- 开关量/整型：PUMP1_RUN=HR50, PUMP2_RUN=HR51, VALVE1=HR52, ALARM_BIT=HR53
INSERT INTO point(device_id,site_id,code,name,addr,dtype,unit,scale_min,scale_max,decimals,rw,deadband) VALUES
 (1,'S001','LEVEL','集水井液位','HR0','float32','m',0,3.5,2,0,0.2),
 (1,'S001','PH','进水PH值','HR2','float32','pH',0,14,2,0,0.2),
 (1,'S001','FLOW','出水流量','HR4','float32','m3/h',0,1000,1,0,0.5),
 (1,'S001','DO','溶解氧','HR6','float32','mg/L',0,12,2,0,0.2),
 (1,'S001','TEMP','水温','HR8','float32','℃',0,60,1,0,0.2),
 (1,'S001','PUMP1_RUN','1号水泵运行','HR50','uint16','',0,1,0,1,0),
 (1,'S001','PUMP2_RUN','2号水泵运行','HR51','uint16','',0,1,0,0,0),
 (1,'S001','VALVE1','1号阀门开度','HR52','uint16','%',0,100,0,1,0),
 (2,'S002','LEVEL','集水井液位','HR0','float32','m',0,3.5,2,0,0.2),
 (2,'S002','PH','进水PH值','HR2','float32','pH',0,14,2,0,0.2),
 (2,'S002','FLOW','出水流量','HR4','float32','m3/h',0,1000,1,0,0.5),
 (2,'S002','DO','溶解氧','HR6','float32','mg/L',0,12,2,0,0.2),
 (2,'S002','PUMP1_RUN','1号水泵运行','HR50','uint16','',0,1,0,1,0),
 (2,'S002','VALVE1','1号阀门开度','HR52','uint16','%',0,100,0,1,0),
 (3,'S003','LEVEL','集水井液位','HR0','float32','m',0,3.5,2,0,0.2),
 (3,'S003','PH','进水PH值','HR2','float32','pH',0,14,2,0,0.2),
 (3,'S003','FLOW','出水流量','HR4','float32','m3/h',0,1000,1,0,0.5),
 (3,'S003','PUMP1_RUN','1号水泵运行','HR50','uint16','',0,1,0,1,0)
ON DUPLICATE KEY UPDATE name=VALUES(name);

-- 组态画面模板（工艺图，逻辑名，实例化时映射到各站点位）
INSERT INTO page(id,name,kind,`json`) VALUES
 (1,'污水处理工艺图-模板','template','{"width":1600,"height":900,"bg":"#0b1622","items":[{"type":"tank","x":120,"y":180,"w":180,"h":280,"var":"LEVEL","min":0,"max":5,"unit":"m","label":"集水井"},{"type":"pump","x":420,"y":380,"w":90,"h":90,"var":"PUMP1_RUN","label":"1号泵"},{"type":"pump","x":420,"y":520,"w":90,"h":90,"var":"PUMP2_RUN","label":"2号泵"},{"type":"pipe","x":300,"y":310,"w":180,"h":20,"var":"PUMP1_RUN"},{"type":"value","x":120,"y":480,"w":180,"h":36,"var":"LEVEL","decimals":2,"unit":"m"},{"type":"value","x":560,"y":180,"w":200,"h":36,"var":"PH","decimals":2,"unit":"pH"},{"type":"value","x":560,"y":240,"w":200,"h":36,"var":"FLOW","decimals":1,"unit":"m3/h"},{"type":"value","x":560,"y":300,"w":200,"h":36,"var":"DO","decimals":2,"unit":"mg/L"},{"type":"value","x":560,"y":360,"w":200,"h":36,"var":"TEMP","decimals":1,"unit":"℃"},{"type":"lamp","x":420,"y":300,"w":40,"h":40,"var":"PUMP1_RUN","label":"泵运行"},{"type":"button","x":420,"y":660,"w":120,"h":44,"var":"PUMP1_RUN","label":"启停1号泵"},{"type":"video","x":900,"y":180,"w":560,"h":320,"label":"现场监控"},{"type":"alarm_list","x":900,"y":540,"w":560,"h":240}]}')
ON DUPLICATE KEY UPDATE `json`=VALUES(`json`);
