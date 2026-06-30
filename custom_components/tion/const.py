"""Constants for the Tion Breezer & MagicAir integration."""

DOMAIN = "tion"
PLATFORMS = ["climate", "sensor", "select", "number"]

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Default polling interval in seconds
DEFAULT_POLLING_INTERVAL = 30

# API Endpoints
API_HOST = "api2.magicair.tion.ru"
API_URL_TOKEN = f"https://{API_HOST}/idsrv/oauth2/token"
API_URL_LOCATION = f"https://{API_HOST}/location"
API_URL_DEVICE_MODE = f"https://{API_HOST}/device/{{guid}}/mode"
API_URL_ZONE_MODE = f"https://{API_HOST}/zone/{{guid}}/mode"
API_URL_TASK = f"https://{API_HOST}/task/{{task_id}}"

# Client ID and secret for Tion Cloud Authentication
CLIENT_ID = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
CLIENT_SECRET = "syRxSrT77P"
