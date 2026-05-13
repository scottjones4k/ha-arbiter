"""Arbiter integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME, CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event

from .client import ArbiterClient, ArbiterClientError
from .const import (
    CONF_CAPABILITY,
    CONF_ENTITY_ID,
    CONF_MAP_OFF,
    CONF_MAP_ON,
    CONF_OBSERVED_ENTITIES,
    CONF_SEVERITY,
    CONF_SUBJECT,
    DEFAULT_SOURCE,
    DOMAIN,
    SERVICE_SEND_PULSE,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_ENTRY_MINOR_VERSION = 1

SEND_PULSE_SCHEMA = vol.Schema(
    {
        vol.Required("capability"): str,
        vol.Required("subject"): str,
        vol.Optional("severity"): vol.Any("debug", "info", "warning", "critical", None),
        vol.Optional("facts", default={}): dict,
        vol.Optional("presentation", default=None): vol.Any(dict, None),
    }
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up global Arbiter services.

    HA's current guidance is to register services/actions in async_setup,
    rather than only after a config entry is loaded.
    """

    async def async_send_pulse_service(call: ServiceCall) -> None:
        """Handle arbiter.send_pulse."""
        entries = hass.config_entries.async_entries(DOMAIN)

        # First cut: use the first configured Arbiter endpoint.
        if not entries:
            raise ArbiterServiceError("No Arbiter integration entry is configured")

        entry = entries[0]
        client: ArbiterClient | None = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("client")
        if client is None:
            raise ArbiterServiceError("Arbiter integration is not loaded")

        payload = _build_pulse_payload(
            capability=call.data["capability"],
            subject=call.data["subject"],
            severity=call.data.get("severity"),
            facts=call.data.get("facts") or {},
            presentation=call.data.get("presentation"),
        )

        await client.async_send_pulse(payload)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_PULSE,
        async_send_pulse_service,
        schema=SEND_PULSE_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Arbiter from a config entry."""
    session = async_get_clientsession(hass)
    client = ArbiterClient(
        session,
        entry.data[CONF_URL],
        entry.data.get(CONF_TOKEN),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "unsubscribers": [],
    }

    _register_observers(hass, entry, client)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Arbiter config entry."""
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if data:
        for unsubscribe in data.get("unsubscribers", []):
            unsubscribe()

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _register_observers(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: ArbiterClient,
) -> None:
    """Register state listeners for configured observed entities."""
    rules = entry.options.get(CONF_OBSERVED_ENTITIES, [])
    data = hass.data[DOMAIN][entry.entry_id]

    for rule in rules:
        entity_id = rule[CONF_ENTITY_ID]

        @callback
        def _state_changed(event, rule=rule):
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")

            if new_state is None:
                return

            # Avoid sending noisy duplicate state_changed events where the state didn't change.
            if old_state is not None and old_state.state == new_state.state:
                return

            hass.async_create_task(
                _async_emit_observed_state(
                    client=client,
                    rule=rule,
                    old_state=old_state,
                    new_state=new_state,
                )
            )

        unsubscribe = async_track_state_change_event(
            hass,
            [entity_id],
            _state_changed,
        )
        data["unsubscribers"].append(unsubscribe)


async def _async_emit_observed_state(
    client: ArbiterClient,
    rule: dict[str, Any],
    old_state,
    new_state,
) -> None:
    """Emit a pulse for an observed entity state change."""
    raw_state = new_state.state
    mapped_state = _map_state(raw_state, rule)

    facts = {
        "state": mapped_state,
        "raw_state": raw_state,
        "old_raw_state": old_state.state if old_state is not None else None,
        "entity_id": new_state.entity_id,
        "friendly_name": new_state.attributes.get(ATTR_FRIENDLY_NAME),
        "source": DEFAULT_SOURCE,
    }

    if "person." in new_state.entity_id:
        facts["person"] = new_state.entity_id.replace("person.", "")

    payload = _build_pulse_payload(
        capability=rule[CONF_CAPABILITY],
        subject=rule[CONF_SUBJECT],
        severity=rule.get(CONF_SEVERITY),
        facts=facts,
        presentation=None,
    )

    try:
        await client.async_send_pulse(payload)
    except ArbiterClientError as exc:
        _LOGGER.warning("Failed to send observed entity pulse to Arbiter: %s", exc)


def _map_state(raw_state: str, rule: dict[str, Any]) -> str:
    """Map HA state to Arbiter state."""
    if raw_state == "on" and rule.get(CONF_MAP_ON):
        return rule[CONF_MAP_ON]
    if raw_state == "off" and rule.get(CONF_MAP_OFF):
        return rule[CONF_MAP_OFF]
    return raw_state


def _build_pulse_payload(
    *,
    capability: str,
    subject: str,
    severity: str | None,
    facts: dict[str, Any],
    presentation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build an Arbiter pulse payload."""
    payload: dict[str, Any] = {
        "capability": capability,
        "subject": subject,
        "facts": {
            "source": DEFAULT_SOURCE,
            **facts,
        },
    }

    if severity:
        payload["severity"] = severity

    if presentation:
        payload["presentation"] = presentation

    return payload


class ArbiterServiceError(HomeAssistantError):
    """Raised when the Arbiter service cannot be used."""
