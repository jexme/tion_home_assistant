"""Support for Tion zone mode select entity."""

import logging
from typing import Any, Dict, List, Optional

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

# Список допустимых режимов зоны
ZONE_MODES = ["auto", "manual"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка платформы select для зон MagicAir."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = data["coordinator"]
    api: TionApi = data["api"]

    entities = []

    for location in coordinator.data:
        for zone in location.get("zones", []):
            # Создаём сущность выбора режима только для зон с устройствами
            if zone.get("devices") and not zone.get("is_virtual", False):
                zone_guid = zone["guid"]
                zone_name = zone.get("name") or "Зона"
                entities.append(
                    TionZoneModeSelect(coordinator, api, zone_guid, zone_name)
                )

    async_add_entities(entities)


class TionZoneModeSelect(CoordinatorEntity, SelectEntity):
    """Сущность выбора режима управления зоной MagicAir (авто/ручной)."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        api: TionApi,
        zone_guid: str,
        zone_name: str,
    ) -> None:
        """Инициализация сущности выбора режима."""
        super().__init__(coordinator)
        self._api = api
        self._zone_guid = zone_guid
        self._zone_name = zone_name

        self._attr_unique_id = f"tion_zone_mode_{zone_guid}"
        self._attr_name = f"{zone_name} - Режим управления"
        self._attr_options = ZONE_MODES
        self._attr_icon = "mdi:home-automation"

    @property
    def device_info(self) -> DeviceInfo:
        """Привязываем к устройству MagicAir зоны."""
        # Ищем MagicAir в данной зоне
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
    def current_option(self) -> Optional[str]:
        """Возвращает текущий режим зоны."""
        zone = self._get_zone_data()
        if zone:
            mode_data = zone.get("mode", {})
            if isinstance(mode_data, dict):
                return mode_data.get("current", "manual")
        return "manual"

    async def async_select_option(self, option: str) -> None:
        """Переключает режим зоны (auto/manual)."""
        _LOGGER.debug("Смена режима зоны %s на: %s", self._zone_guid, option)
        zone = self._get_zone_data()
        if not zone:
            _LOGGER.error("Зона %s не найдена в кэше", self._zone_guid)
            return

        mode_data = zone.get("mode", {})
        auto_set = mode_data.get("auto_set", {}) if isinstance(mode_data, dict) else {}
        # Читаем текущий целевой CO2 из настроек авторежима
        current_co2 = int(auto_set.get("co2", 900)) if isinstance(auto_set, dict) else 900

        try:
            await self._api.async_send_zone_mode(
                self._zone_guid, {"mode": option, "co2": current_co2}
            )
            _LOGGER.info("Режим зоны %s успешно изменён на %s", self._zone_guid, option)
            # Обновляем локально в кэше для мгновенного отображения
            if isinstance(mode_data, dict):
                mode_data["current"] = option
            self.async_write_ha_state()
            # Запрашиваем обновление данных от сервера
            await self.coordinator.async_request_refresh()
        except TionApiError as err:
            _LOGGER.error("Ошибка смены режима зоны %s: %s", self._zone_guid, err)
