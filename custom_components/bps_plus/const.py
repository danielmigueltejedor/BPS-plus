from __future__ import annotations

DOMAIN = "bps-plus"

# Configuración expuesta en el config flow / options
CONF_BASE_URL = "base_url"          # URL externa (Nabu Casa / Nginx / etc.)
CONF_TOKEN = "token"                # Long-lived access token de HA
CONF_UPDATE_INTERVAL = "update_interval"  # Intervalo de actualización en segundos

DEFAULT_UPDATE_INTERVAL = 2  # por ejemplo, 2 s
