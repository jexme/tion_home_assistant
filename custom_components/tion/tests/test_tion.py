import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import asyncio

# Добавляем пути для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from custom_components.tion.climate import TionClimateEntity
from custom_components.tion.select import TionBreezerModeSpeedSelect
from homeassistant.components.climate import HVACMode


class TestTionIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.coordinator = MagicMock()
        self.coordinator.async_request_refresh = AsyncMock()
        self.api = MagicMock()
        self.api.async_send_breezer_mode = AsyncMock(return_value="task-123")
        self.api.async_send_zone_mode = AsyncMock(return_value="task-456")

        # Инициализируем тестовые данные координатора без персональных данных
        self.device_guid = "test-breezer-guid"
        self.zone_guid = "test-zone-guid"
        self.device_name = "Test Breezer"
        
        self.mock_device_data = {
            "guid": self.device_guid,
            "name": self.device_name,
            "type": "breezer",
            "max_speed": 4,
            "t_min": 0,
            "t_max": 30,
            "data": {
                "is_on": True,
                "speed": 2,
                "t_set": 20,
                "t_in": 15,
                "t_out": 22,
                "heater_enabled": False,
                "filter_need_replace": False,
                "gate": 2,
                "speed_min_set": 0,
                "speed_max_set": 4
            }
        }

        self.mock_zone_data = {
            "guid": self.zone_guid,
            "name": "Test Zone",
            "mode": {
                "current": "auto",
                "auto_set": {
                    "co2": 800
                }
            },
            "devices": [self.mock_device_data]
        }

        self.coordinator.data = [
            {
                "guid": "test-location-guid",
                "name": "Test Location",
                "zones": [self.mock_zone_data]
            }
        ]

        # Настраиваем фейковый hass с отслеживанием фоновых задач
        self.hass = MagicMock()
        self.created_tasks = []

        def mock_create_task(coro):
            task = asyncio.create_task(coro)
            self.created_tasks.append(task)
            return task

        self.hass.async_create_task = mock_create_task

    async def async_tearDown(self):
        # Ожидаем завершения всех фоновых задач, чтобы не было RuntimeWarning
        if self.created_tasks:
            await asyncio.gather(*self.created_tasks, return_exceptions=True)

    def test_climate_entity_properties(self):
        """Проверка базовых свойств климатической сущности."""
        entity = TionClimateEntity(
            self.coordinator, self.api, self.device_guid, self.device_name, "breezer", self.zone_guid
        )
        
        self.assertEqual(entity.name, self.device_name)
        self.assertTrue(entity.is_on)
        self.assertEqual(entity.target_temperature, 20)
        self.assertEqual(entity.current_temperature, 22)
        # В авторежиме fan_mode должен возвращать "Auto"
        self.assertEqual(entity.fan_mode, "Auto")
        self.assertEqual(entity.fan_modes, ["Auto", "1", "2", "3", "4"])

    @patch("custom_components.tion.climate.time.time", return_value=100.0)
    async def test_climate_set_hvac_mode_off(self, mock_time):
        """Проверка выключения климатической сущности."""
        entity = TionClimateEntity(
            self.coordinator, self.api, self.device_guid, self.device_name, "breezer", self.zone_guid
        )
        entity.hass = self.hass
        entity.async_write_ha_state = MagicMock()
        
        # Выключаем устройство
        await entity.async_set_hvac_mode(HVACMode.OFF)
        
        # Проверяем оптимистичное состояние
        self.assertFalse(entity._opt_state["is_on"])
        self.assertEqual(entity._opt_state["speed"], 0)
        
        # Ждем завершения фоновой отправки
        await asyncio.gather(*self.created_tasks)
        
        # Проверяем отправленный API-пакет. Для обычного бризера heater_mode должен быть "heat"
        self.api.async_send_breezer_mode.assert_called_once_with(
            self.device_guid,
            {
                "is_on": False,
                "heater_enabled": False,
                "heater_mode": "heat",
                "t_set": 20,
                "speed": 1,
                "speed_min_set": 0,
                "speed_max_set": 4,
                "gate": 2
            }
        )

    @patch("custom_components.tion.climate.time.time", return_value=100.0)
    async def test_climate_set_hvac_mode_off_4s(self, mock_time):
        """Проверка выключения климатической сущности для модели 4S (должен использоваться maintenance)."""
        entity = TionClimateEntity(
            self.coordinator, self.api, self.device_guid, self.device_name, "breezer4s", self.zone_guid
        )
        entity.hass = self.hass
        entity.async_write_ha_state = MagicMock()
        
        # Выключаем устройство
        await entity.async_set_hvac_mode(HVACMode.OFF)
        
        # Ждем завершения фоновой отправки
        await asyncio.gather(*self.created_tasks)
        
        # Проверяем отправленный API-пакет. Для модели 4S heater_mode должен быть "maintenance"
        self.api.async_send_breezer_mode.assert_called_once_with(
            self.device_guid,
            {
                "is_on": False,
                "heater_enabled": False,
                "heater_mode": "maintenance",
                "t_set": 20,
                "speed": 1,
                "speed_min_set": 0,
                "speed_max_set": 4,
                "gate": 2
            }
        )

    @patch("custom_components.tion.climate.time.time", return_value=100.0)
    async def test_climate_set_fan_mode_numeric(self, mock_time):
        """Проверка установки ручной скорости на климате."""
        entity = TionClimateEntity(
            self.coordinator, self.api, self.device_guid, self.device_name, "breezer", self.zone_guid
        )
        entity.hass = self.hass
        entity.async_write_ha_state = MagicMock()
        
        # Устанавливаем скорость 3
        await entity.async_set_fan_mode("3")
        
        self.assertEqual(entity._opt_state["speed"], 3)
        self.assertTrue(entity._opt_state["is_on"])
        
        # Ждем завершения фоновой отправки
        await asyncio.gather(*self.created_tasks)
        
        # Проверяем, что зона переведена в ручной режим (manual)
        self.api.async_send_zone_mode.assert_called_once_with(
            self.zone_guid,
            {"mode": "manual", "co2": 800}
        )
        
        # Проверяем отправку скорости на бризер
        self.api.async_send_breezer_mode.assert_called_once_with(
            self.device_guid,
            {
                "is_on": True,
                "heater_enabled": False,
                "heater_mode": "heat",
                "t_set": 20,
                "speed": 3,
                "speed_min_set": 0,
                "speed_max_set": 4,
                "gate": 2
            }
        )

    @patch("custom_components.tion.select.time.time", return_value=100.0)
    async def test_select_mode_speed_auto(self, mock_time):
        """Проверка перевода в Auto через Select-сущность."""
        select_entity = TionBreezerModeSpeedSelect(
            self.coordinator, self.api, self.device_guid, self.device_name, self.zone_guid
        )
        select_entity.hass = self.hass
        select_entity.async_write_ha_state = MagicMock()
        
        # Выбираем Auto
        await select_entity.async_select_option("Auto")
        
        self.assertEqual(select_entity._opt_option, "Auto")
        
        # Ждем завершения фоновой отправки
        await asyncio.gather(*self.created_tasks)
        
        # Должна вызваться только отправка режима зоны в auto
        self.api.async_send_zone_mode.assert_called_once_with(
            self.zone_guid,
            {"mode": "auto", "co2": 800}
        )
        self.api.async_send_breezer_mode.assert_not_called()

    @patch("custom_components.tion.select.time.time", return_value=100.0)
    async def test_select_mode_speed_numeric(self, mock_time):
        """Проверка перевода скорости через Select-сущность."""
        select_entity = TionBreezerModeSpeedSelect(
            self.coordinator, self.api, self.device_guid, self.device_name, self.zone_guid
        )
        select_entity.hass = self.hass
        select_entity.async_write_ha_state = MagicMock()
        
        # Выбираем скорость 4
        await select_entity.async_select_option("4")
        
        # Ждем завершения фоновой отправки
        await asyncio.gather(*self.created_tasks)
        
        # Сначала зона должна перевестись в manual
        self.api.async_send_zone_mode.assert_called_once_with(
            self.zone_guid,
            {"mode": "manual", "co2": 800}
        )
        
        # Затем на бризер должна уйти скорость 4
        self.api.async_send_breezer_mode.assert_called_once_with(
            self.device_guid,
            {
                "is_on": True,
                "heater_enabled": False,
                "heater_mode": "heat",
                "t_set": 20,
                "speed": 4,
                "speed_min_set": 0,
                "speed_max_set": 4,
                "gate": 2,
            }
        )


if __name__ == "__main__":
    unittest.main()
