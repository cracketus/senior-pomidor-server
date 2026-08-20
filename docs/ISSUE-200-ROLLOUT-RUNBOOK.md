# Issue #200 — проверка и обновление Linux-сервера

Инструкция для Ubuntu/Linux production host. Выполняйте по одному шагу.

Пути: активный релиз /srv/apps/senior-pomidor/app; secrets /srv/secrets/senior-pomidor/runtime.env; backups /srv/backups/senior-pomidor; systemd unit senior-pomidor.service.

## 0. Подключение и базовая проверка

Все команды выполняются после SSH-подключения к серверу.

    ssh <user>@<server>
    cd /srv/apps/senior-pomidor/app
    sudo docker info
    sudo docker compose version
    sudo systemctl is-active senior-pomidor
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml ps
    curl -fsS http://192.168.0.50:8000/health
    curl -fsS http://192.168.0.50:8000/ready

Если Docker, systemd, /health или /ready не работают — остановитесь.

## 1. Сохраните текущую версию и данные

    cd /srv/apps/senior-pomidor/app
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U senior_pomidor -d senior_pomidor -c "SELECT version_num FROM alembic_version;"
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U senior_pomidor -d senior_pomidor -c "SELECT count(*) FROM telemetry_events;"
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U senior_pomidor -d senior_pomidor -c "SELECT count(*) FROM pod_readings;"
    readlink -f /srv/apps/senior-pomidor/app

Запишите вывод.

## 2. Проверьте backup

Не обновляйте сервер без свежего backup.

    sudo find /srv/backups/senior-pomidor -maxdepth 2 -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n' | sort
    sudo find /srv/backups/senior-pomidor -name SHA256SUMS -print
    sudo systemctl status senior-pomidor-backup-daily.timer --no-pager
    sudo systemctl status senior-pomidor-backup-weekly.timer --no-pager

Если свежего проверенного migration backup нет — остановитесь и используйте штатную root-owned backup/restore automation. Не создавайте backup в каталоге приложения.

## 3. Подготовьте и проверьте release

На ПК скачайте release bundle и checksum из принятого PR/release. Не используйте latest.

На сервере:

    sudo install -d -o root -g root -m 0750 /srv/apps/senior-pomidor/releases/.incoming
    sudo install -o root -g root -m 0644 senior-pomidor-runtime-vX.Y.Z.tar.gz senior-pomidor-runtime-vX.Y.Z.tar.gz.sha256 /srv/apps/senior-pomidor/releases/.incoming/
    cd /srv/apps/senior-pomidor/releases/.incoming
    sha256sum -c senior-pomidor-runtime-vX.Y.Z.tar.gz.sha256

Checksum должен завершиться OK.

## 4. Установите release и миграцию

    sudo /srv/automation/scripts/senior-pomidor/install-release.sh senior-pomidor-runtime-vX.Y.Z.tar.gz senior-pomidor-runtime-vX.Y.Z.tar.gz.sha256
    readlink -f /srv/apps/senior-pomidor/app
    sudo systemctl restart senior-pomidor.service
    sudo systemctl status senior-pomidor.service --no-pager
    sudo journalctl -u senior-pomidor.service -n 200 --no-pager

Проверьте миграцию и новую колонку:

    cd /srv/apps/senior-pomidor/app
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U senior_pomidor -d senior_pomidor -c "SELECT version_num FROM alembic_version;"
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U senior_pomidor -d senior_pomidor -c "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='telemetry_events' AND column_name='record_id';"

Ожидаются 0009_telemetry_record_id и nullable record_id. Не запускайте alembic downgrade.

## 5. Health-check

    curl -fsS http://192.168.0.50:8000/health
    curl -fsS http://192.168.0.50:8000/ready
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml logs --tail 100 api
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml logs --tail 100 worker

Не продолжайте при traceback, ошибке PostgreSQL/MQTT или постоянных 503.

## 6. Canary accepted/duplicate

Создайте временный payload:

    cat > /tmp/telemetry-canary.json <<'JSON'
    {
      "schema_version": "senior-pomidor.edge.telemetry.v2",
      "record_id": "canary:server-update:REPLACE_ME",
      "device_id": "pi-001",
      "timestamp_utc": "2026-08-20T12:00:00Z",
      "pods": {"pod_1": {"enabled": true, "metrics": {"soil_moisture_percent": 42.5, "air_vpd_kpa": 1.1}}},
      "system_health": {
        "rpi_core": {"cpu_temp_c": 45.0, "wifi_rssi_dbm": -55.0},
        "network": {"wifi_connected": true, "wifi_profile_count": 2, "internet_reachable": true, "dns_resolution_ok": true, "last_recovery_result": "not_needed", "last_recovery_exit_code": 0},
        "errors": []
      }
    }
    JSON
    sed -i "s/REPLACE_ME/$(date -u +%Y%m%dT%H%M%SZ)/" /tmp/telemetry-canary.json

Отправьте два раза:

    curl -i -X POST http://192.168.0.50:8000/api/v1/edge/telemetry -H 'Content-Type: application/json' --data-binary @/tmp/telemetry-canary.json
    curl -i -X POST http://192.168.0.50:8000/api/v1/edge/telemetry -H 'Content-Type: application/json' --data-binary @/tmp/telemetry-canary.json

Ожидается первый HTTP 202 accepted, второй HTTP 202 duplicate.

Проверьте одну строку:

    record_id=$(jq -r .record_id /tmp/telemetry-canary.json)
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U senior_pomidor -d senior_pomidor -c "SELECT record_id, count(*) FROM telemetry_events WHERE record_id='$record_id' GROUP BY record_id;"

Ожидается count = 1. Иначе остановитесь.

## 7. Edge и наблюдение

    cd /srv/apps/senior-pomidor/app
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml exec -T api python -m tools.edge_readiness --api-base-url http://192.168.0.50.1:8000 --mqtt-host mosquitto --photo-storage-dir data/photos
    sudo journalctl -u senior-pomidor.service --since "15 minutes ago" --no-pager
    sudo docker compose --env-file /srv/secrets/senior-pomidor/runtime.env -f docker-compose.yml -f docker-compose.prod.yml logs --since 15m api worker

Наблюдайте 15–30 минут. Следите за retry, HTTP 503, record_id_conflict, падением MQTT worker и отсутствием новых записей.

## 8. Откат

Откатывайте только application release:

    sudo /srv/automation/scripts/senior-pomidor/rollback-release.sh <PREVIOUS_RELEASE>
    sudo systemctl restart senior-pomidor.service
    sudo systemctl status senior-pomidor.service --no-pager
    curl -fsS http://192.168.0.50:8000/ready

Не удаляйте record_id, не запускайте alembic downgrade, docker compose down -v, удаление volumes или SQL DELETE. Edge spool оставьте на месте.

## Продолжать rollout можно только если

- backup найден и проверен;
- release checksum совпал;
- миграция успешна;
- /ready исправен;
- canary дал accepted, повтор дал duplicate;
- в базе ровно одна строка;
- старый payload без record_id принимается;
- нет всплеска 503 и traceback.

Если хотя бы один пункт не выполнен — остановите rollout и сохраните edge backlog.

