"""Support for Tion Breezer climate entity."""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Задержка в секундах для удержания оптимистичного состояния в интерфейсе
OPTIMISTIC_TIMEOUT = 6.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка платформы climate на основе записи конфигурации."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = data["coordinator"]
    api = data["api"]

    entities = []
    # Обходим все локации и устройства, чтобы найти бризеры
    for location in coordinator.data:
        for zone in location.get("zones", []):
            for device in zone.get("devices", []):
                dev_type = device.get("type", "")
                if "breezer" in dev_type or "O2" in dev_type:
                    entities.append(
                        TionClimateEntity(
                            coordinator,
                            api,
                            device["guid"],
                            device["name"],
                            dev_type,
                            zone["guid"],
                        )
                    )

    async_add_entities(entities)


class TionClimateEntity(CoordinatorEntity, ClimateEntity):
    """Представление бризера Tion как климатической сущности HA."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_WHOLE

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api,
        guid: str,
        name: str,
        device_type: str,
        zone_guid: str,
    ) -> None:
        """Инициализация сущности."""
        super().__init__(coordinator)
        self._api = api
        self._guid = guid
        self._name = name
        self._device_type = device_type
        self._zone_guid = zone_guid

        # Уникальный ID в HA
        self._attr_unique_id = f"tion_breezer_{guid}"

        # Поддерживаемые функции
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        # Список доступных режимов HVAC
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY, HVACMode.HEAT]

        # Локальный кэш для оптимистичного состояния (для устранения скачков в UI)
        self._opt_state: Dict[str, Any] = {}
        self._opt_timestamp: float = 0.0

    @property
    def name(self) -> str:
        """Возвращает имя устройства."""
        return self._name

    @property
    def device_info(self) -> DeviceInfo:
        """Информация об устройстве для связывания сущностей."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._guid)},
            name=self._name,
            manufacturer="Tion",
            model=self._device_type.capitalize(),
        )

    def _get_device_data(self) -> Optional[Dict[str, Any]]:
        """Ищет данные текущего устройства в кэше координатора."""
        for location in self.coordinator.data:
            for zone in location.get("zones", []):
                for device in zone.get("devices", []):
                    if device.get("guid") == self._guid:
                        return device
        return None

    def _get_zone_data(self) -> Optional[Dict[str, Any]]:
        """Ищет данные текущей зоны в кэше координатора."""
        for location in self.coordinator.data:
            for zone in location.get("zones", []):
                if zone.get("guid") == self._zone_guid:
                    return zone
        return None


    # --- Свойства климатической сущности ---

    @property
    def is_on(self) -> bool:
        """Возвращает статус питания (включен или выключен)."""
        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            if "is_on" in self._opt_state:
                return self._opt_state["is_on"]

        data = self._get_device_data()
        if data:
            return data.get("data", {}).get("is_on", False)
        return False

    @property
    def hvac_mode(self) -> HVACMode:
        """Возвращает текущий режим HVAC."""
        if not self.is_on:
            return HVACMode.OFF

        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            if "heater_enabled" in self._opt_state:
                return HVACMode.HEAT if self._opt_state["heater_enabled"] else HVACMode.FAN_ONLY

        data = self._get_device_data()
        if data:
            heater_enabled = data.get("data", {}).get("heater_enabled", False)
            return HVACMode.HEAT if heater_enabled else HVACMode.FAN_ONLY

        return HVACMode.OFF

    @property
    def target_temperature(self) -> Optional[float]:
        """Возвращает целевую температуру."""
        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            if "t_set" in self._opt_state:
                return self._opt_state["t_set"]

        data = self._get_device_data()
        if data:
            return data.get("data", {}).get("t_set")
        return None

    @property
    def current_temperature(self) -> Optional[float]:
        """Возвращает температуру выходящего воздуха (t_out) как текущую температуру."""
        data = self._get_device_data()
        if data:
            return data.get("data", {}).get("t_out")
        return None

    @property
    def fan_mode(self) -> Optional[str]:
        """Возвращает текущую скорость вентилятора."""
        if not self.is_on:
            return "0"

        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            if "speed" in self._opt_state:
                return str(self._opt_state["speed"])

        data = self._get_device_data()
        if data:
            return str(int(data.get("data", {}).get("speed", 1)))
        return None

    @property
    def fan_modes(self) -> Optional[List[str]]:
        """Возвращает список поддерживаемых скоростей."""
        data = self._get_device_data()
        if data:
            max_speed = data.get("max_speed", 6)
            return [str(i) for i in range(1, max_speed + 1)]
        return ["1", "2", "3", "4", "5", "6"]

    @property
    def min_temp(self) -> float:
        """Возвращает минимальную целевую температуру."""
        data = self._get_device_data()
        if data:
            return data.get("t_min", 0.0)
        return 0.0

    @property
    def max_temp(self) -> float:
        """Возвращает максимальную целевую температуру."""
        data = self._get_device_data()
        if data:
            return data.get("t_max", 30.0)
        return 30.0

    # --- Методы управления ---

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Установка нового режима работы."""
        _LOGGER.debug("Установка режима HVAC: %s", hvac_mode)

        if hvac_mode == HVACMode.OFF:
            self._opt_state["is_on"] = False
            self._opt_state["speed"] = 0
        else:
            self._opt_state["is_on"] = True
            # При включении выставляем скорость 1, если она была 0
            current_speed = int(self.fan_mode or 1)
            self._opt_state["speed"] = current_speed if current_speed > 0 else 1
            self._opt_state["heater_enabled"] = (hvac_mode == HVACMode.HEAT)

        self._opt_timestamp = time.time()
        self.async_write_ha_state()

        # Запуск задачи в фоне
        self.hass.async_create_task(self._async_apply_changes())

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Установка скорости вентилятора."""
        _LOGGER.debug("Установка скорости вентилятора: %s", fan_mode)
        try:
            speed = int(fan_mode)
        except ValueError:
            speed = 1

        self._opt_state["speed"] = speed
        self._opt_state["is_on"] = (speed > 0)
        self._opt_timestamp = time.time()
        self.async_write_ha_state()

        self.hass.async_create_task(self._async_apply_changes())

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Установка целевой температуры."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        _LOGGER.debug("Установка целевой температуры: %s", temperature)
        self._opt_state["t_set"] = int(temperature + 0.5)
        self._opt_timestamp = time.time()
        self.async_write_ha_state()

        self.hass.async_create_task(self._async_apply_changes())

    async def async_turn_on(self) -> None:
        """Включение бризера."""
        await self.async_set_hvac_mode(HVACMode.FAN_ONLY)

    async def async_turn_off(self) -> None:
        """Выключение бризера."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    # --- Логика отправки изменений ---

    async def _async_apply_changes(self) -> None:
        """Собирает оптимистичное состояние и отправляет его на Tion Cloud API."""
        data = self._get_device_data()
        if not data:
            return

        device_data = data.get("data", {})

        # Проверяем режим зоны. Если зона находится в авторежиме (auto),
        # перед отправкой настроек бризера переключаем зону в ручной режим (manual)
        zone_data = self._get_zone_data()
        if zone_data:
            zone_mode_data = zone_data.get("mode", {})
            current_mode = zone_mode_data.get("current") if isinstance(zone_mode_data, dict) else zone_mode_data
            if current_mode == "auto":
                _LOGGER.info("Зона %s находится в авторежиме (auto). Переключаем в ручной режим (manual)...", self._zone_guid)
                try:
                    # В API Tion для переключения зоны нужно также передать целевое co2 (берем текущую установку или 900)
                    auto_set = zone_mode_data.get("auto_set", {}) if isinstance(zone_mode_data, dict) else {}
                    current_co2 = int(auto_set.get("co2", 900)) if isinstance(auto_set, dict) else 900
                    await self._api.async_send_zone_mode(self._zone_guid, {"mode": "manual", "co2": current_co2})
                    # Обновляем локально в кэше
                    if isinstance(zone_mode_data, dict):
                        zone_mode_data["current"] = "manual"
                except Exception as zone_err:
                    _LOGGER.error("Не удалось переключить зону %s в ручной режим: %s", self._zone_guid, zone_err)

        # Объединяем текущие данные из кэша с нашими оптимистичными переопределениями
        is_on = self._opt_state.get("is_on", device_data.get("is_on", False))
        speed = self._opt_state.get("speed", int(device_data.get("speed", 1)))
        if not is_on:
            speed = 0

        heater_enabled = self._opt_state.get("heater_enabled", device_data.get("heater_enabled", False))
        t_set = self._opt_state.get("t_set", device_data.get("t_set", 20))

        # Формируем пакет параметров для отправки в Tion API
        command_data = {
            "is_on": is_on,
            "heater_enabled": heater_enabled,
            "heater_mode": "heat" if heater_enabled else "maintenance",
            "t_set": int(t_set),
            "speed": speed if speed > 0 else 1,  # В API Tion выключенный статус регулируется is_on, а скорость > 0
            "speed_min_set": int(device_data.get("speed_min_set", 0)),
            "speed_max_set": int(device_data.get("speed_max_set", data.get("max_speed", 6))),
        }

        # Если задан ручной режим, добавляем управление заслонкой (gate)
        gate = device_data.get("gate")
        if gate is not None:
            command_data["gate"] = gate

        try:
            # Асинхронно отправляем в очередь API
            await self._api.async_send_breezer_mode(self._guid, command_data)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Не удалось отправить команду на бризер %s: %s", self._guid, err)
            # В случае ошибки сбрасываем оптимистичный таймер, чтобы вернуть реальное состояние
            self._opt_timestamp = 0.0
            self.async_write_ha_state()
            return

        # Планируем отложенный опрос сервера через 4 секунды, чтобы дать облаку обновить состояние
        await asyncio.sleep(4.0)
        _LOGGER.debug("Запуск фонового обновления состояния после команды")
        await self.coordinator.async_request_refresh()
