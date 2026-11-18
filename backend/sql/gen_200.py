# -*- coding: utf-8 -*-
"""批量站点/点位生成器（P1-7）
   生成可导入的 SQL 文件（UTF-8），导入时务必带 --default-character-set=utf8mb4

   用法：
     python3 gen_200.py --sites 200 --points 1000 --out /tmp/seed_200.sql
     python3 gen_200.py --sites 10  --points 200  --out /tmp/seed_10.sql --port-base 16000

   点位构成（默认 1000）：模拟量 700（float32，HR0 起，步长2）+ 开关量 300（uint16，HR2000 起）
   地址按 PLC 编址规则连续排，便于采集端地址合并
"""
import argparse
import datetime

ANALOG_UNITS = ["m", "pH", "m3/h", "mg/L", "℃", "kPa", "%", "A"]
ANALOG_NAMES = ["液位", "进水PH值", "出水流量", "溶解氧", "水温", "压力", "阀门开度", "电流"]


def gen(sites, points, port_base, out, active_sites=0, site_start=1):
    analog = int(points * 0.7)
    digital = points - analog
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("SET NAMES utf8mb4;\n")
        f.write(f"-- 自动生成：{sites} 站点 × {points} 点位（模拟量 {analog} / 开关量 {digital}）\n")
        f.write(f"-- 生成时间 {now}\n\n")

        # ---- 站点 ----
        for i in range(site_start, site_start + sites):
            sid = f"S{i:03d}"
            group = (i - 1) // 10 + 1
            port = port_base + i - site_start
            f.write(
                "INSERT INTO site(id,name,group_id,address,protocol,plc_ip,plc_port,status,remark) "
                f"VALUES ('{sid}','第{i}污水处理厂',{group},'批量生成-{group}号片区','modbus_tcp',"
                f"'127.0.0.1',{port},0,'批量生成') "
                "ON DUPLICATE KEY UPDATE name=VALUES(name), plc_port=VALUES(plc_port);\n")

        # ---- 设备（每站 1 台 PLC）----
        for i in range(site_start, site_start + sites):
            sid = f"S{i:03d}"
            port = port_base + i - site_start
            f.write(
                "INSERT INTO device(site_id,name,model,protocol,ip,port,slave_id,default_poll_ms,enabled) "
                f"VALUES ('{sid}','{sid}-PLC','模拟PLC','modbus_tcp','127.0.0.1',{port},1,5000,1) "
                "ON DUPLICATE KEY UPDATE port=VALUES(port), default_poll_ms=VALUES(default_poll_ms);\n")

        # ---- 点位（按站点分批，多行 INSERT；device_id 用 @did 变量避免 20 万次子查询）----
        for i in range(site_start, site_start + sites):
            sid = f"S{i:03d}"
            f.write(f"\n-- ===== {sid} 点位 =====\n")
            f.write(f"SET @did = (SELECT id FROM device WHERE site_id='{sid}' LIMIT 1);\n")
            rows = []
            for k in range(analog):
                idx = k % len(ANALOG_NAMES)
                rows.append((f"AI{k + 1:04d}", f"模拟量{k + 1}-{ANALOG_NAMES[idx]}",
                             f"HR{100 + k * 2}", "float32", ANALOG_UNITS[idx], 0, 100, 2, 0, 2.0))
            for k in range(digital):
                rows.append((f"DI{k + 1:04d}", f"开关量{k + 1}-设备",
                             f"HR{2000 + k}", "uint16", "", 0, 1, 0, 1 if k % 50 == 0 else 0, 0))
            for b in range(0, len(rows), 500):
                chunk = rows[b:b + 500]
                vals = ",".join(
                    f"(@did,'{sid}','{r[0]}','{r[1]}','{r[2]}','{r[3]}','{r[4]}',{r[5]},{r[6]},{r[7]},{r[8]},{r[9]})"
                    for r in chunk)
                f.write("INSERT INTO point(device_id,site_id,code,name,addr,dtype,unit,"
                        "scale_min,scale_max,decimals,rw,deadband) VALUES " + vals + " "
                        "ON DUPLICATE KEY UPDATE name=VALUES(name), unit=VALUES(unit);\n")
    print(f"已生成 {out}：{sites} 站点 × {points} 点位 = {sites * points} 个点位")
    if 0 < active_sites < sites:
        with open(out, "a", encoding="utf-8", newline="\n") as f:
            # 只保留前 N 站采集，其余先停用（避免没有真实 PLC 时刷出几十万条 q=1）
            f.write(f"\nUPDATE device d JOIN site s ON s.id=d.site_id "
                    f"SET d.enabled=0 WHERE CAST(SUBSTRING(s.id,2) AS UNSIGNED) > {active_sites};\n")
        print(f"已停用第 {active_sites + 1}~{sites} 站采集（device.enabled=0）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=int, default=200)
    ap.add_argument("--points", type=int, default=1000)
    ap.add_argument("--port-base", type=int, default=15020)
    ap.add_argument("--site-start", type=int, default=1, help="站点起始编号")
    ap.add_argument("--active-sites", type=int, default=0,
                    help="只启用前 N 个站点的采集，0 表示全部启用")
    ap.add_argument("--out", default="/tmp/seed_200.sql")
    a = ap.parse_args()
    gen(a.sites, a.points, a.port_base, a.out, a.active_sites, a.site_start)
