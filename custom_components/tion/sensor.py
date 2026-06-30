"""Support for Tion sensors."""

import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Настройка платформы sensor на основе записи конфигурации."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = data["coordinator"]

    entities = []

    for location in coordinator.data:
        for zone in location.get("zones", []):
            for device in zone.get("devices", []):
                dev_type = device.get("type", "")
                guid = device["guid"]
                name = device["name"]

                if "co2" in dev_type or "magic" in dev_type.lower():
                    # Датчики для MagicAir
                    entities.append(TionMagicAirSensor(coordinator, guid, name, dev_type, "co2"))
                    entities.append(TionMagicAirSensor(coordinator, guid, name, dev_type, "temperature"))
                    entities.append(TionMagicAirSensor(coordinator, guid, name, dev_type, "humidity"))
                elif "breezer" in dev_type or "O2" in dev_type:
                    # Датчики для Бризера
                    entities.append(TionBreezerSensor(coordinator, guid, name, dev_type, "temp_in"))
                    entities.append(TionBreezerSensor(coordinator, guid, name, dev_type, "temp_out"))
                    entities.append(TionBreezerSensor(coordinator, guid, name, dev_type, "filter"))

    async_add_entities(entities)


class TionSensorBase(CoordinatorEntity, SensorEntity):
    """Базовый класс для всех сенсоров Tion."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        guid: str,
        name: str,
        device_type: str,
        sensor_type: str,
    ) -> None:
        """Инициализация сенсора."""
        super().__init__(coordinator)
        self._guid = guid
        self._device_name = name
        self._device_type = device_type
        self._sensor_type = sensor_type
        self._attr_unique_id = f"tion_{guid}_{sensor_type}"

    @property
    def device_info(self) -> DeviceInfo:
        """Информация об устройстве."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._guid)},
            name=self._device_name,
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


class TionMagicAirSensor(TionSensorBase):
    """Сенсор для базовой станции MagicAir."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        guid: str,
        name: str,
        device_type: str,
        sensor_type: str,
    ) -> None:
        """Инициализация сенсора MagicAir."""
        super().__init__(coordinator, guid, name, device_type, sensor_type)

        if sensor_type == "co2":
            self._attr_name = f"{name} CO2"
            self._attr_device_class = SensorDeviceClass.CO2
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "ppm"
        elif sensor_type == "temperature":
            self._attr_name = f"{name} Temperature"
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif sensor_type == "humidity":
            self._attr_name = f"{name} Humidity"
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self) -> Optional[float]:
        """Возвращает текущее значение сенсора."""
        data = self._get_device_data()
        if not data:
            return None

        device_data = data.get("data", {})
        if self._sensor_type == "co2":
            return device_data.get("co2")
        elif self._sensor_type == "temperature":
            return device_data.get("temperature")
        elif self._sensor_type == "humidity":
            return device_data.get("humidity")
        return None


class TionBreezerSensor(TionSensorBase):
    """Сенсор для бризера Tion."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        guid: str,
        name: str,
        device_type: str,
        sensor_type: str,
    ) -> None:
        """Инициализация сенсора бризера."""
        super().__init__(coordinator, guid, name, device_type, sensor_type)

        if sensor_type == "temp_in":
            self._attr_name = f"{name} - Температура входящего воздуха"
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif sensor_type == "temp_out":
            self._attr_name = f"{name} - Температура выходящего воздуха"
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif sensor_type == "filter":
            self._attr_name = f"{name} - Состояние фильтра"
            self._attr_icon = "mdi:air-filter"

    @property
    def native_value(self) -> Any:
        """Возвращает текущее значение сенсора."""
        data = self._get_device_data()
        if not data:
            return None

        device_data = data.get("data", {})
        if self._sensor_type == "temp_in":
            return device_data.get("t_in")
        elif self._sensor_type == "temp_out":
            return device_data.get("t_out")
        elif self._sensor_type == "filter":
            need_replace = device_data.get("filter_need_replace", False)
            return "Замена" if need_replace else "ОК"
        return None
