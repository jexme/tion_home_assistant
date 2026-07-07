import logging
import asyncio
import time
from typing import Any, Dict, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
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
    """Настройка платформы select."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = data["coordinator"]
    api: TionApi = data["api"]

    entities = []

    for location in coordinator.data:
        for zone in location.get("zones", []):
            if zone.get("devices") and not zone.get("is_virtual", False):
                zone_guid = zone["guid"]
                
                for device in zone.get("devices", []):
                    dev_type = device.get("type", "")
                    if "breezer" in dev_type.lower() or "o2" in dev_type.lower() or "4s" in dev_type.lower():
                        entities.append(
                            TionBreezerModeSpeedSelect(coordinator, api, device["guid"], device["name"], zone_guid)
                        )

    async_add_entities(entities)


class TionBreezerModeSpeedSelect(CoordinatorEntity, SelectEntity):
    """Единая сущность выбора режима управления (Auto) или ручной скорости (1-max_speed)."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: TionApi,
        device_guid: str,
        device_name: str,
        zone_guid: str,
    ) -> None:
        """Инициализация сущности."""
        super().__init__(coordinator)
        self._api = api
        self._device_guid = device_guid
        self._device_name = device_name
        self._zone_guid = zone_guid

        self._attr_unique_id = f"tion_mode_speed_{device_guid}"
        self._attr_name = f"{device_name} - Режим и Скорость"
        self._attr_icon = "mdi:fan-auto"
        
        self._opt_option: Optional[str] = None
        self._opt_timestamp: float = 0

    @property
    def device_info(self) -> DeviceInfo:
        """Привязываем к устройству бризера."""
        return DeviceInfo(identifiers={(DOMAIN, self._device_guid)})

    def _get_device_data(self) -> Optional[Dict[str, Any]]:
        for location in self.coordinator.data:
            for zone in location.get("zones", []):
                for device in zone.get("devices", []):
                    if device.get("guid") == self._device_guid:
                        return device
        return None

    def _get_zone_data(self) -> Optional[Dict[str, Any]]:
        for location in self.coordinator.data:
            for zone in location.get("zones", []):
                if zone.get("guid") == self._zone_guid:
                    return zone
        return None

    @property
    def options(self) -> list[str]:
        """Возвращает список ['Auto', '1', '2', ..., 'max_speed']."""
        device_data = self._get_device_data()
        max_speed = 6
        if device_data:
            max_speed = int(device_data.get("max_speed", 6))
        return ["Auto"] + [str(i) for i in range(1, max_speed + 1)]

    @property
    def current_option(self) -> Optional[str]:
        """Возвращает 'Auto' или текущую скорость как строку."""
        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            return self._opt_option

        zone = self._get_zone_data()
        if zone:
            mode_data = zone.get("mode", {})
            if isinstance(mode_data, dict):
                if mode_data.get("current") == "auto":
                    return "Auto"

        device_data = self._get_device_data()
        if device_data:
            data = device_data.get("data", {})
            if isinstance(data, dict):
                if not data.get("is_on", True):
                    return "Auto"  # Если выключен, пусть покажет Auto (или лучше что-то другое, но оставим Auto по умолчанию, либо 1)
                return str(data.get("speed", 1))
        return "Auto"

    async def async_select_option(self, option: str) -> None:
        """Пользователь выбрал опцию."""
        self._opt_option = option
        self._opt_timestamp = time.time()
        self.async_write_ha_state()
        
        self.hass.async_create_task(self._async_apply_option(option))

    async def _async_apply_option(self, option: str) -> None:
        _LOGGER.debug("Выбрана опция %s для бризера %s", option, self._device_guid)

        zone = self._get_zone_data()
        if not zone:
            return

        mode_data = zone.get("mode", {})
        auto_set = mode_data.get("auto_set", {}) if isinstance(mode_data, dict) else {}
        current_co2 = int(auto_set.get("co2", 900)) if isinstance(auto_set, dict) else 900

        try:
            if option == "Auto":
                # Переводим только зону в авто
                await self._api.async_send_zone_mode(
                    self._zone_guid, {"mode": "auto", "co2": current_co2}
                )
            else:
                # 1. Переводим зону в manual
                await self._api.async_send_zone_mode(
                    self._zone_guid, {"mode": "manual", "co2": current_co2}
                )
                
                # 2. Выставляем скорость на бризере
                speed_target = int(option)
                device_data = self._get_device_data()
                if device_data:
                    dev_type = device_data.get("type", "")
                    is_4s = "4s" in dev_type.lower()
                    data = device_data.get("data", {})
                    heater_enabled = data.get("heater_enabled", False)
                    heater_mode = "heat"
                    if not heater_enabled and is_4s:
                        heater_mode = "maintenance"

                    payload = {
                        "is_on": True,
                        "heater_enabled": heater_enabled,
                        "heater_mode": heater_mode,
                        "t_set": int(data.get("t_set", 20)),
                        "speed": speed_target,
                        "speed_min_set": int(data.get("speed_min_set", 0)),
                        "speed_max_set": int(data.get("speed_max_set", device_data.get("max_speed", 6))),
                    }
                    gate = data.get("gate")
                    if gate is not None:
                        payload["gate"] = gate
                        
                    await self._api.async_send_breezer_mode(self._device_guid, payload)

            await asyncio.sleep(4)
            await self.coordinator.async_request_refresh()
        except TionApiError as err:
            _LOGGER.error("Ошибка применения опции %s: %s", option, err)
