"""The Tion Breezer & MagicAir integration."""

from datetime import timedelta
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TionApi, TionApiError
from .const import DEFAULT_POLLING_INTERVAL, DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Настройка интеграции Tion на основе записи конфигурации."""
    hass.data.setdefault(DOMAIN, {})

    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    api = TionApi(session, email, password)

    async def async_update_data():
        """Периодическое получение данных от Tion Cloud."""
        try:
            # Запрашиваем состояние всех локаций и устройств
            return await api.async_get_data()
        except TionApiError as err:
            raise UpdateFailed(f"Ошибка получения обновлений от Tion Cloud: {err}") from err

    # Создаем координатор для совместного обновления данных сущностями
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"Tion {email}",
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_POLLING_INTERVAL),
    )

    # Выполняем первый опрос для наполнения кэша данных
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    # Настраиваем платформы (climate, sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Выгрузка интеграции Tion."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
