#!/usr/bin/env bash
set -e

# Опеределяем пути
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TESTS_DIR="${PROJECT_DIR}/custom_components/tion/tests"

echo "=== 1. Копирование обновленного кода и тестов в контейнер ==="
# Сначала чистим старую папку в докере, если она осталась
docker exec homeassistant rm -rf /config/custom_components/tion/tests
# Копируем свежую папку тестов
docker cp "${TESTS_DIR}" homeassistant:/config/custom_components/tion/

echo "=== 2. Запуск тестов внутри контейнера Home Assistant ==="
docker exec -it homeassistant python3 -m unittest /config/custom_components/tion/tests/test_tion.py

echo "=== Все тесты успешно пройдены! ==="
