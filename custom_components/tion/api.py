"""Asynchronous client for Tion Cloud API."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import aiohttp

from .const import (
    API_URL_DEVICE_MODE,
    API_URL_LOCATION,
    API_URL_TOKEN,
    API_URL_ZONE_MODE,
    CLIENT_ID,
    CLIENT_SECRET,
)

_LOGGER = logging.getLogger(__name__)

class TionApiError(Exception):
    """Базовая ошибка для Tion API."""


class TionAuthError(TionApiError):
    """Ошибка авторизации Tion API."""


class TionApi:
    """Асинхронный клиент для взаимодействия с Tion Cloud API."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str):
        """Инициализация клиента."""
        self._session = session
        self._email = email
        self._password = password
        self.authorization: Optional[str] = None
        self._data: List[Dict[str, Any]] = []

    @property
    def headers(self) -> Dict[str, str]:
        """Возвращает HTTP-заголовки для запросов к Tion API."""
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU",
            "Content-Type": "application/json",
            "Origin": "https://magicair.tion.ru",
            "Referer": "https://magicair.tion.ru/dashboard/overview",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if self.authorization:
            headers["Authorization"] = self.authorization
        return headers

    async def async_login(self) -> bool:
        """Авторизация в Tion Cloud и получение токена доступа."""
        data = {
            "username": self._email,
            "password": self._password,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "password",
        }
        _LOGGER.debug("Попытка входа для пользователя %s", self._email)
        try:
            async with self._session.post(
                API_URL_TOKEN, data=data, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    js = await response.json()
                    self.authorization = f"{js['token_type']} {js['access_token']}"
                    _LOGGER.info("Авторизация успешна. Получен новый токен доступа.")
                    return True
                else:
                    try:
                        error_js = await response.json()
                        error_desc = error_js.get("error_description", str(error_js))
                    except Exception:
                        error_desc = await response.text()
                    _LOGGER.error(
                        "Ошибка авторизации: код %s, ответ: %s",
                        response.status,
                        error_desc,
                    )
                    raise TionAuthError(f"Ошибка авторизации ({response.status}): {error_desc}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("Сетевая ошибка при попытке авторизации: %s", err)
            raise TionApiError(f"Не удалось подключиться к серверу авторизации: {err}")

    async def async_get_data(self) -> List[Dict[str, Any]]:
        """Получение текущего состояния всех локаций и устройств."""
        if not self.authorization:
            await self.async_login()

        _LOGGER.debug("Запрос данных о локациях с Tion Cloud")
        try:
            async with self._session.get(
                API_URL_LOCATION, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    self._data = await response.json()
                    return self._data
                elif response.status == 401:
                    _LOGGER.info("Токен истек, пытаемся переавторизоваться...")
                    if await self.async_login():
                        return await self.async_get_data()
                else:
                    _LOGGER.error("Не удалось получить данные: статус %s", response.status)
                    raise TionApiError(f"Ошибка получения данных: статус {response.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("Ошибка сети при получении данных: %s", err)
            raise TionApiError(f"Не удалось получить данные от Tion Cloud: {err}")
        return []

    async def async_send_breezer_mode(self, guid: str, data: Dict[str, Any]) -> str:
        """Отправка настроек режима работы бризера. Возвращает task_id задачи."""
        if not self.authorization:
            await self.async_login()

        url = API_URL_DEVICE_MODE.format(guid=guid)
        _LOGGER.debug("Отправка настроек для бризера %s: %s", guid, data)
        try:
            async with self._session.post(
                url, json=data, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    js = await response.json()
                    status = js.get("status")
                    if status == "queued":
                        task_id = js.get("task_id")
                        _LOGGER.debug("Команда успешно добавлена в очередь, task_id: %s", task_id)
                        return task_id
                    else:
                        description = js.get("description", "Нет описания")
                        _LOGGER.error("Не удалось поставить команду в очередь: %s (%s)", status, description)
                        raise TionApiError(f"Ошибка постановки команды в очередь: {status} ({description})")
                elif response.status == 401:
                    _LOGGER.info("Токен истек при отправке команды, обновляем токен...")
                    if await self.async_login():
                        return await self.async_send_breezer_mode(guid, data)
                else:
                    _LOGGER.error("Ошибка при отправке команды: статус %s", response.status)
                    raise TionApiError(f"Ошибка отправки команды: статус {response.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("Сетевая ошибка при отправке команды: %s", err)
            raise TionApiError(f"Сетевой сбой при управлении бризером: {err}")
        raise TionApiError("Неизвестная ошибка при отправке команды")

    async def async_send_zone_mode(self, guid: str, data: Dict[str, Any]) -> str:
        """Отправка настроек режима работы зоны (авто/ручной). Возвращает task_id."""
        if not self.authorization:
            await self.async_login()

        url = API_URL_ZONE_MODE.format(guid=guid)
        _LOGGER.debug("Отправка настроек для зоны %s: %s", guid, data)
        try:
            async with self._session.post(
                url, json=data, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    js = await response.json()
                    status = js.get("status")
                    if status == "queued":
                        task_id = js.get("task_id")
                        return task_id
                    else:
                        raise TionApiError(f"Ошибка очереди зоны: {status}")
                elif response.status == 401:
                    if await self.async_login():
                        return await self.async_send_zone_mode(guid, data)
                else:
                    raise TionApiError(f"Ошибка отправки режима зоны: статус {response.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise TionApiError(f"Сетевой сбой при управлении зоной: {err}")
        raise TionApiError("Неизвестная ошибка при отправке режима зоны")
