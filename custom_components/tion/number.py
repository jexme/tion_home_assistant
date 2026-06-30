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
                if device.get("type") in ("co2mb",) or "magic" in device.get("type", "").lower():
                    return device.get("guid")
        return None

    @property
    def native_value(self) -> Optional[float]:
        """Возвращает текущий целевой уровень CO₂."""
        if time.time() - self._opt_timestamp < OPTIMISTIC_TIMEOUT:
            if self._opt_co2 is not None:
                return self._opt_co2

        zone = self._get_zone_data()
        if zone:
            mode_data = zone.get("mode", {})
            auto_set = mode_data.get("auto_set", {}) if isinstance(mode_data, dict) else {}
            if isinstance(auto_set, dict):
                return float(auto_set.get("co2", 900))
        return 900.0

    async def async_set_native_value(self, value: float) -> None:
        """Устанавливает новый целевой уровень CO₂ для зоны."""
        target_co2 = int(value)
        _LOGGER.debug("Установка целевого CO2 для зоны %s: %d", self._zone_guid, target_co2)

        self._opt_co2 = float(target_co2)
        self._opt_timestamp = time.time()
        self.async_write_ha_state()

        zone = self._get_zone_data()
        if not zone:
            _LOGGER.error("Зона %s не найдена в кэше", self._zone_guid)
            return

        mode_data = zone.get("mode", {})
        current_mode = mode_data.get("current", "manual") if isinstance(mode_data, dict) else "manual"

        try:
            await self._api.async_send_zone_mode(
                self._zone_guid, {"mode": current_mode, "co2": target_co2}
            )
            _LOGGER.info("Целевой CO2 для зоны %s успешно изменён на %d", self._zone_guid, target_co2)
            
            if isinstance(mode_data, dict) and "auto_set" in mode_data:
                if isinstance(mode_data["auto_set"], dict):
                    mode_data["auto_set"]["co2"] = target_co2
                    
            # Затем отправляем команду бризеру
            await self._api.async_send_breezer_mode(self._device_guid, payload)
            _LOGGER.info("Скорость бризера %s изменена на %d", self._device_guid, speed_target)
            
            await asyncio.sleep(4)
            await self.coordinator.async_request_refresh()
        except TionApiError as err:
            _LOGGER.error("Ошибка установки скорости для бризера %s: %s", self._device_guid, err)
