from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_BASE_URL,
    CONF_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
)


class BpsPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow para BPS-Plus."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].strip()
            token = user_input[CONF_TOKEN].strip()
            interval = user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

            if not base_url.startswith(("http://", "https://")):
                errors[CONF_BASE_URL] = "invalid_url"

            if not token:
                errors[CONF_TOKEN] = "required"

            if interval < 1 or interval > 60:
                errors[CONF_UPDATE_INTERVAL] = "range"

            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="BPS-Plus",
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_TOKEN: token,
                        CONF_UPDATE_INTERVAL: interval,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL): str,
                vol.Required(CONF_TOKEN): str,
                vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.Coerce(int),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return BpsPlusOptionsFlow(entry)


class BpsPlusOptionsFlow(config_entries.OptionsFlow):
    """Opciones de BPS-Plus."""

    def __init__(self, entry):
        self.entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self.entry.data
        options = self.entry.options

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL, default=options.get(CONF_BASE_URL, data.get(CONF_BASE_URL))): str,
                vol.Required(CONF_TOKEN, default=options.get(CONF_TOKEN, data.get(CONF_TOKEN))): str,
                vol.Optional(CONF_UPDATE_INTERVAL, default=options.get(CONF_UPDATE_INTERVAL, data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))): vol.Coerce(int),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
