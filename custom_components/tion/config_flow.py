"""Config flow for Tion Breezer & MagicAir integration."""

import logging
from typing import Any, Dict, Optional
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TionApi, TionAuthError, TionApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class TionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Класс управления конфигурацией интеграции Tion."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Шаг ручной настройки пользователем."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Проверяем, не настроена ли уже эта интеграция для данного email
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = TionApi(
                session, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )

            try:
                # Пробуем авторизоваться для проверки данных
                await api.async_login()
            except TionAuthError:
                errors["base"] = "invalid_auth"
            except TionApiError:
                errors["base"] = "cannot_connect"
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Непредвиденная ошибка при проверке: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
