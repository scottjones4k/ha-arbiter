"""Config flow for Arbiter."""

from __future__ import annotations

from typing import Any

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

CONF_HEALTH_ENTITY_ID = "health_entity_id"
CONF_HEALTH_MAP_ON = "health_map_on"
CONF_HEALTH_MAP_OFF = "health_map_off"
CONF_HEALTH_MAP_UNKNOWN = "health_map_unknown"
CONF_HEALTH_MAP_UNAVAILABLE = "health_map_unavailable"


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
            except Exception:  # noqa: BLE001
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
        self._edit_index: int | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Show options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_observed_entity",
                "edit_observed_entity",
                "remove_observed_entity",
            ],
        )

    async def async_step_add_observed_entity(
        self, user_input: dict[str, Any] | None = None
    ):
        """Add an observed entity."""
        errors: dict[str, str] = {}

        if user_input is not None:
            item, errors = self._build_observed_entity(user_input)

            if not errors:
                self._observed.append(item)
                return self._save_options()

        return self.async_show_form(
            step_id="add_observed_entity",
            data_schema=self._observed_entity_schema(),
            errors=errors,
        )

    async def async_step_edit_observed_entity(
        self, user_input: dict[str, Any] | None = None
    ):
        """Choose an observed entity to edit."""
        if not self._observed:
            return self._save_options()

        options = self._observed_options()

        if user_input is not None:
            self._edit_index = int(user_input["rule"])
            return await self.async_step_edit_observed_entity_details()

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
            step_id="edit_observed_entity",
            data_schema=schema,
        )

    async def async_step_edit_observed_entity_details(
        self, user_input: dict[str, Any] | None = None
    ):
        """Edit an observed entity."""
        if self._edit_index is None or self._edit_index >= len(self._observed):
            return await self.async_step_init()

        existing = self._observed[self._edit_index]
        errors: dict[str, str] = {}

        if user_input is not None:
            item, errors = self._build_observed_entity(user_input)

            if not errors:
                self._observed[self._edit_index] = item
                self._edit_index = None
                return self._save_options()

        return self.async_show_form(
            step_id="edit_observed_entity_details",
            data_schema=self._observed_entity_schema(existing),
            errors=errors,
        )

    async def async_step_remove_observed_entity(
        self, user_input: dict[str, Any] | None = None
    ):
        """Remove an observed entity."""
        if not self._observed:
            return self._save_options()

        options = self._observed_options()

        if user_input is not None:
            remove_index = int(user_input["rule"])
            self._observed.pop(remove_index)
            return self._save_options()

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

    def _save_options(self):
        """Persist options."""
        return self.async_create_entry(
            title="",
            data={
                **self._config_entry.options,
                CONF_OBSERVED_ENTITIES: self._observed,
            },
        )

    def _observed_options(self) -> list[dict[str, str]]:
        """Build dropdown options for existing observed entities."""
        return [
            {
                "value": str(index),
                "label": (
                    f"{item.get(CONF_ENTITY_ID)} → "
                    f"{item.get(CONF_CAPABILITY)} / "
                    f"{item.get(CONF_SUBJECT)}"
                ),
            }
            for index, item in enumerate(self._observed)
        ]

    def _build_observed_entity(
        self,
        user_input: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Build an observed entity config item from form input."""
        errors: dict[str, str] = {}

        entity_id = user_input[CONF_ENTITY_ID]
        capability = user_input[CONF_CAPABILITY].strip()
        subject = user_input[CONF_SUBJECT].strip()

        if not capability:
            errors[CONF_CAPABILITY] = "required"

        if not subject:
            errors[CONF_SUBJECT] = "required"

        health_entity_id = user_input.get(CONF_HEALTH_ENTITY_ID)

        item = {
            CONF_ENTITY_ID: entity_id,
            CONF_CAPABILITY: capability,
            CONF_SUBJECT: subject,
            CONF_SEVERITY: user_input.get(CONF_SEVERITY) or None,
            CONF_MAP_ON: user_input.get(CONF_MAP_ON) or None,
            CONF_MAP_OFF: user_input.get(CONF_MAP_OFF) or None,
        }

        if health_entity_id:
            item.update(
                {
                    CONF_HEALTH_ENTITY_ID: health_entity_id,
                    CONF_HEALTH_MAP_ON: (
                        user_input.get(CONF_HEALTH_MAP_ON) or None
                    ),
                    CONF_HEALTH_MAP_OFF: (
                        user_input.get(CONF_HEALTH_MAP_OFF) or None
                    ),
                    CONF_HEALTH_MAP_UNKNOWN: (
                        user_input.get(CONF_HEALTH_MAP_UNKNOWN) or None
                    ),
                    CONF_HEALTH_MAP_UNAVAILABLE: (
                        user_input.get(CONF_HEALTH_MAP_UNAVAILABLE) or None
                    ),
                }
            )

        return item, errors

    def _observed_entity_schema(
        self,
        existing: dict[str, Any] | None = None,
    ) -> vol.Schema:
        """Build add/edit schema."""
        existing = existing or {}

        return vol.Schema(
            {
                vol.Required(
                    CONF_ENTITY_ID,
                    default=existing.get(CONF_ENTITY_ID),
                ): selector.EntitySelector(),
                vol.Required(
                    CONF_CAPABILITY,
                    default=existing.get(CONF_CAPABILITY, ""),
                ): str,
                vol.Required(
                    CONF_SUBJECT,
                    default=existing.get(CONF_SUBJECT, ""),
                ): str,
                vol.Optional(
                    CONF_SEVERITY,
                    default=existing.get(CONF_SEVERITY),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["debug", "info", "warning", "critical"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MAP_ON,
                    default=existing.get(CONF_MAP_ON, ""),
                ): str,
                vol.Optional(
                    CONF_MAP_OFF,
                    default=existing.get(CONF_MAP_OFF, ""),
                ): str,

                # Optional linked health/status entity.
                vol.Optional(
                    CONF_HEALTH_ENTITY_ID,
                    default=existing.get(CONF_HEALTH_ENTITY_ID),
                ): selector.EntitySelector(),
                vol.Optional(
                    CONF_HEALTH_MAP_ON,
                    default=existing.get(CONF_HEALTH_MAP_ON, "online"),
                ): str,
                vol.Optional(
                    CONF_HEALTH_MAP_OFF,
                    default=existing.get(CONF_HEALTH_MAP_OFF, "offline"),
                ): str,
                vol.Optional(
                    CONF_HEALTH_MAP_UNKNOWN,
                    default=existing.get(CONF_HEALTH_MAP_UNKNOWN, "unknown"),
                ): str,
                vol.Optional(
                    CONF_HEALTH_MAP_UNAVAILABLE,
                    default=existing.get(
                        CONF_HEALTH_MAP_UNAVAILABLE,
                        "offline",
                    ),
                ): str,
            }
        )