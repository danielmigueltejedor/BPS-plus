from __future__ import annotations

DOMAIN = "bps_plus"

# Configuración expuesta en el config flow / options
CONF_BASE_URL = "base_url"          # URL externa (Nabu Casa / Nginx / etc.)
CONF_TOKEN = "token"                # Long-lived access token de HA
CONF_UPDATE_INTERVAL = "update_interval"  # Intervalo de actualización en segundos
CONF_STALE_AFTER = "stale_after"    # segundos antes de marcar la distancia como no disponible
CONF_SCAN_INTERVAL = "scan_interval"  # cadencia con la que HA refresca cada sensor

DEFAULT_UPDATE_INTERVAL = 2  # por ejemplo, 2 s
DEFAULT_STALE_AFTER = 60     # mantener última distancia hasta 60 s sin advertisement
DEFAULT_SCAN_INTERVAL = 2    # poll cada 2 s (default HA es 30 s, demasiado lento)
