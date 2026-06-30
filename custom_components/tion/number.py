"""Support for Tion zone CO2 target level number entity."""

import logging
import time
import asyncio
from typing import Any, Dict, Optional

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .api import TionApi, TionApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

OPTIMISTIC_TIMEOUT = 6


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка платформы number для целевого уровня CO₂ зоны MagicAir."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = data["coordinator"]
    api: TionApi = data["api"]

    entities = []

    for location in coordinator.data:
        for zone in location.get("zones", []):
            if zone.get("devices") and not zone.get("is_virtual", False):
                zone_guid = zone["guid"]
                zone_name = zone.get("name") or "Зона"
                entities.append(
                    TionZoneCO2Target(coordinator, api, zone_guid, zone_name)
                )

                for device in zone.get("devices", []):
                    dev_type = device.get("type", "")
                    if "breezer" in dev_type.lower() or "o2" in dev_type.lower() or "4s" in dev_type.lower():
                        entities.append(
                            TionBreezerSpeed(coordinator, api, device["guid"], device["name"], zone_guid)
                        )

    async_add_entities(entities)


class TionZoneCO2Target(CoordinatorEntity, NumberEntity):
    """Сущность для задания целевого уровня CO₂ авторежима зоны MagicAir."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: TionApi,
        zone_guid: str,
        zone_name: str,
    ) -> None:
        """Инициализация сущности целевого CO₂."""
        super().__init__(coordinator)
        self._api = api
        self._zone_guid = zone_guid
        self._zone_name = zone_name

        self._attr_unique_id = f"tion_zone_co2_target_{zone_guid}"
        self._attr_name = f"{zone_name} - Целевой уровень CO₂"
        self._attr_icon = "mdi:molecule-co2"
        self._attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
        self._attr_native_min_value = 400
        self._attr_native_max_value = 1500
        self._attr_native_step = 50
        self._attr_mode = NumberMode.SLIDER
        
        self._opt_co2: Optional[float] = None
        self._opt_timestamp: float = 0

    @property
    def device_info(self) -> DeviceInfo:
        """Привязываем к устройству MagicAir зоны."""
        magicair_guid = self._get_magicair_guid()
        if magicair_guid:
            return DeviceInfo(identifiers={(DOMAIN, magicair_guid)})
        return DeviceInfo(identifiers={(DOMAIN, self._zone_guid)})

    def _get_zone_data(self) -> Optional[Dict[str, Any]]:
        """Ищет данные текущей зоны в кэше координатора."""
        for location in self.coordinator.data:
            for zone in location.get("zones", []):
                if zone.get("guid") == self._zone_guid:
                    return zone
        return None

    def _get_magicair_guid(self) -> Optional[str]:
        """Ищет GUID устройства MagicAir в данной зоне."""
        zone = self._get_zone_data()
        if zone:
            for device in zone.get("devices", []):
                if device.get("type") == "co2mb" or "magic" in device.get("type", "").lower():
                    return device.get("guid")
        return None

    @property
    def native_value(self) -> Optional[float]:
        """Возвращает текущий целевой уровень CO₂."""
        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            return self._opt_co2

        zone = self._get_zone_data()
        if zone:
            mode_data = zone.get("mode", {})
            if isinstance(mode_data, dict):
                auto_set = mode_data.get("auto_set", {})
                if isinstance(auto_set, dict):
                    return auto_set.get("co2")
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Устанавливает новый целевой уровень CO₂ для зоны."""
        co2_target = int(value)
        
        self._opt_co2 = float(co2_target)
        self._opt_timestamp = time.time()
        self.async_write_ha_state()
        
        self.hass.async_create_task(self._async_apply_co2(co2_target))

    async def _async_apply_co2(self, co2_target: int) -> None:
        _LOGGER.debug("Установка целевого CO₂ для зоны %s: %d ppm", self._zone_guid, co2_target)

        zone = self._get_zone_data()
        if not zone:
            _LOGGER.error("Зона %s не найдена в кэше", self._zone_guid)
            return

        mode_data = zone.get("mode", {})
        current_mode = mode_data.get("current", "manual") if isinstance(mode_data, dict) else "manual"

        try:
            await self._api.async_send_zone_mode(
                self._zone_guid, {"mode": current_mode, "co2": co2_target}
            )
            _LOGGER.info(
                "Целевой CO₂ зоны %s изменён на %d ppm (режим: %s)",
                self._zone_guid, co2_target, current_mode,
            )
            await asyncio.sleep(4)
            await self.coordinator.async_request_refresh()
        except TionApiError as err:
            _LOGGER.error("Ошибка установки целевого CO₂ для зоны %s: %s", self._zone_guid, err)


class TionBreezerSpeed(CoordinatorEntity, NumberEntity):
    """Сущность для задания скорости вентилятора бризера."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: TionApi,
        device_guid: str,
        device_name: str,
        zone_guid: str,
    ) -> None:
        """Инициализация сущности скорости бризера."""
        super().__init__(coordinator)
        self._api = api
        self._device_guid = device_guid
        self._device_name = device_name
        self._zone_guid = zone_guid

        self._attr_unique_id = f"tion_breezer_speed_{device_guid}"
        self._attr_name = f"{device_name} - Скорость работы"
        self._attr_icon = "mdi:fan"
        self._attr_native_min_value = 0
        self._attr_native_step = 1
        self._attr_mode = NumberMode.SLIDER
        
        self._opt_speed: Optional[float] = None
        self._opt_is_on: Optional[bool] = None
        self._opt_timestamp: float = 0

    @property
    def device_info(self) -> DeviceInfo:
        """Привязываем к устройству бризера."""
        return DeviceInfo(identifiers={(DOMAIN, self._device_guid)})

    def _get_device_data(self) -> Optional[Dict[str, Any]]:
        """Ищет данные текущего устройства в кэше координатора."""
        for location in self.coordinator.data:
            for zone in location.get("zones", []):
                for device in zone.get("devices", []):
                    if device.get("guid") == self._device_guid:
                        return device
        return None

    @property
    def native_max_value(self) -> float:
        """Динамически получаем максимальную скорость бризера."""
        device_data = self._get_device_data()
        if device_data:
            return float(device_data.get("max_speed", 6))
        return 6.0

    @property
    def native_value(self) -> Optional[float]:
        """Возвращает текущую скорость."""
        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            if not self._opt_is_on:
                return 0.0
            return self._opt_speed

        device_data = self._get_device_data()
        if device_data:
            data = device_data.get("data", {})
            if isinstance(data, dict):
                if not data.get("is_on", True):
                    return 0.0
                return float(data.get("speed", 1))
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Устанавливает новую скорость бризера."""
        speed_target = int(value)
        is_on = speed_target > 0
        
        self._opt_speed = float(speed_target)
        self._opt_is_on = is_on
        self._opt_timestamp = time.time()
        self.async_write_ha_state()
        
        self.hass.async_create_task(self._async_apply_speed(speed_target, is_on))

    async def _async_apply_speed(self, speed_target: int, is_on: bool) -> None:
        _LOGGER.debug("Установка скорости для бризера %s: %d", self._device_guid, speed_target)

        device_data = self._get_device_data()
        if not device_data:
            _LOGGER.error("Устройство %s не найдено в кэше", self._device_guid)
            return

        data = device_data.get("data", {})
        
        payload = {
            "is_on": is_on,
            "heater_enabled": data.get("heater_enabled", False),
            "heater_mode": "heat" if data.get("heater_enabled", False) else "maintenance",
            "t_set": int(data.get("t_set", 20)),
            "speed": speed_target if speed_target > 0 else 1,
            "speed_min_set": int(data.get("speed_min_set", 0)),
            "speed_max_set": int(data.get("speed_max_set", device_data.get("max_speed", 6))),
        }
        
        gate = data.get("gate")
        if gate is not None:
            payload["gate"] = gate

        try:
            # Сначала проверяем режим зоны и переключаем в manual, если нужно
            zone_mode_data = {}
            for location in self.coordinator.data:
                for zone in location.get("zones", []):
                    if zone.get("guid") == self._zone_guid:
                        zone_mode_data = zone.get("mode", {})
                        break
            
            if zone_mode_data and isinstance(zone_mode_data, dict):
                current_mode = zone_mode_data.get("current")
                if current_mode == "auto":
                    _LOGGER.info("Переключение зоны %s в manual перед изменением скорости", self._zone_guid)
                    auto_set = zone_mode_data.get("auto_set", {})
                    current_co2 = int(auto_set.get("co2", 900)) if isinstance(auto_set, dict) else 900
                    await self._api.async_send_zone_mode(
                        self._zone_guid, {"mode": "manual", "co2": current_co2}
                    )
                    
            # Затем отправляем команду бризеру
            await self._api.async_send_breezer_mode(self._device_guid, payload)
            _LOGGER.info("Скорость бризера %s изменена на %d", self._device_guid, speed_target)
            
            await asyncio.sleep(4)
            await self.coordinator.async_request_refresh()
        except TionApiError as err:
            _LOGGER.error("Ошибка установки скорости для бризера %s: %s", self._device_guid, err)
