#!/usr/bin/env bash
# /opt/plant/backup.sh —— 每日备份 MySQL + TDengine 校验，保留 7 天
set -euo pipefail
BACKUP_DIR=/opt/plant-data/backup
DATE=$(date +%F)
install -d $BACKUP_DIR

docker exec plant-mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --databases plant' \
  | gzip > $BACKUP_DIR/plant-$DATE.sql.gz

# TDengine 校验：走 REST（口令从 .env 读；改密后 taos CLI 不带口令会认证失败）
TD_PWD=$(grep -E '^TDENGINE_PWD=' /opt/plant/.env 2>/dev/null | cut -d= -f2-)
curl -s -u "root:$TD_PWD" --data-raw 'show plant.stables' http://127.0.0.1:6041/rest/sql \
  > $BACKUP_DIR/tdengine-check-$DATE.txt 2>&1 || true

find $BACKUP_DIR -name 'plant-*.sql.gz' -mtime +7 -delete
echo "$(date '+%F %T') backup done: $BACKUP_DIR/plant-$DATE.sql.gz" >> $BACKUP_DIR/backup.log
