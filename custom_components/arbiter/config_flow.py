"""Config flow for Arbiter."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_URL, CONF_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .client import ArbiterClient, ArbiterClientError
from .const import (
    CONF_CAPABILITY,
    CONF_ENTITY_ID,
    CONF_MAP_OFF,
    CONF_MAP_ON,
    CONF_OBSERVED_ENTITIES,
    CONF_SEVERITY,
    CONF_SUBJECT,
    DOMAIN,
)


class ArbiterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an Arbiter config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            token = user_input.get(CONF_TOKEN) or None

            session = async_get_clientsession(self.hass)
            client = ArbiterClient(session, url, token)

            try:
                await client.async_test_connection()
            except ArbiterClientError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - HA convention in config flows
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Arbiter",
                    data={
                        CONF_URL: url,
                        CONF_TOKEN: token,
                    },
                    options={
                        CONF_OBSERVED_ENTITIES: [],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL): str,
                vol.Optional(CONF_TOKEN): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Create the options flow."""
        return ArbiterOptionsFlow(config_entry)


class ArbiterOptionsFlow(config_entries.OptionsFlow):
    """Options flow for observed entities."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._observed = list(
            config_entry.options.get(CONF_OBSERVED_ENTITIES, [])
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_observed_entity", "remove_observed_entity"],
        )

    async def async_step_add_observed_entity(
        self, user_input: dict[str, Any] | None = None
    ):
        """Add an observed entity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            entity_id = user_input[CONF_ENTITY_ID]
            capability = user_input[CONF_CAPABILITY].strip()
            subject = user_input[CONF_SUBJECT].strip()

            if not capability:
                errors[CONF_CAPABILITY] = "required"
            elif not subject:
                errors[CONF_SUBJECT] = "required"
            else:
                self._observed.append(
                    {
                        CONF_ENTITY_ID: entity_id,
                        CONF_CAPABILITY: capability,
                        CONF_SUBJECT: subject,
                        CONF_SEVERITY: user_input.get(CONF_SEVERITY) or None,
                        CONF_MAP_ON: user_input.get(CONF_MAP_ON) or None,
                        CONF_MAP_OFF: user_input.get(CONF_MAP_OFF) or None,
                    }
                )

                return self.async_create_entry(
                    title="",
                    data={
                        **self._config_entry.options,
                        CONF_OBSERVED_ENTITIES: self._observed,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): selector.EntitySelector(),
                vol.Required(CONF_CAPABILITY): str,
                vol.Required(CONF_SUBJECT): str,
                vol.Optional(CONF_SEVERITY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["debug", "info", "warning", "critical"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_MAP_ON, default=""): str,
                vol.Optional(CONF_MAP_OFF, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="add_observed_entity",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_remove_observed_entity(
        self, user_input: dict[str, Any] | None = None
    ):
        """Remove an observed entity."""
        if not self._observed:
            return self.async_create_entry(
                title="",
                data={
                    **self._config_entry.options,
                    CONF_OBSERVED_ENTITIES: [],
                },
            )

        options = [
            {
                "value": str(index),
                "label": f"{item.get(CONF_ENTITY_ID)} → {item.get(CONF_CAPABILITY)} / {item.get(CONF_SUBJECT)}",
            }
            for index, item in enumerate(self._observed)
        ]

        if user_input is not None:
            remove_index = int(user_input["rule"])
            self._observed.pop(remove_index)

            return self.async_create_entry(
                title="",
                data={
                    **self._config_entry.options,
                    CONF_OBSERVED_ENTITIES: self._observed,
                },
            )

        schema = vol.Schema(
            {
                vol.Required("rule"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="remove_observed_entity",
            data_schema=schema,
        )
