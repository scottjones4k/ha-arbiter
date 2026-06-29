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
    CONF_HEALTH_ENTITY_ID,
    CONF_HEALTH_MAP_OFF,
    CONF_HEALTH_MAP_ON,
    CONF_HEALTH_MAP_UNAVAILABLE,
    CONF_HEALTH_MAP_UNKNOWN,
    CONF_MAP_OFF,
    CONF_MAP_ON,
    CONF_OBSERVED_ENTITIES,
    CONF_SEVERITY,
    CONF_SUBJECT,
    DEFAULT_SOURCE,
    DOMAIN,
    HEALTH_CAPABILITY,
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
    _LOGGER.info("Setting up Arbiter global services")

    async def async_send_pulse_service(call: ServiceCall) -> None:
        """Handle arbiter.send_pulse."""
        _LOGGER.info(
            "Arbiter send_pulse service called: capability=%s subject=%s severity=%s",
            call.data.get("capability"),
            call.data.get("subject"),
            call.data.get("severity"),
        )

        entries = hass.config_entries.async_entries(DOMAIN)

        # First cut: use the first configured Arbiter endpoint.
        if not entries:
            _LOGGER.error("Arbiter send_pulse service failed: no config entries")
            raise ArbiterServiceError("No Arbiter integration entry is configured")

        entry = entries[0]
        client: ArbiterClient | None = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("client")
        if client is None:
            _LOGGER.error(
                "Arbiter send_pulse service failed: integration entry %s is not loaded",
                entry.entry_id,
            )
            raise ArbiterServiceError("Arbiter integration is not loaded")

        payload = _build_pulse_payload(
            capability=call.data["capability"],
            subject=call.data["subject"],
            severity=call.data.get("severity"),
            facts=call.data.get("facts") or {},
            presentation=call.data.get("presentation"),
        )

        _LOGGER.debug("Sending manual Arbiter pulse payload: %s", payload)

        try:
            await client.async_send_pulse(payload)
        except ArbiterClientError:
            _LOGGER.exception(
                "Failed to send manual Arbiter pulse: capability=%s subject=%s",
                call.data.get("capability"),
                call.data.get("subject"),
            )
            raise

        _LOGGER.info(
            "Successfully sent manual Arbiter pulse: capability=%s subject=%s",
            call.data.get("capability"),
            call.data.get("subject"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_PULSE,
        async_send_pulse_service,
        schema=SEND_PULSE_SCHEMA,
    )

    _LOGGER.info("Arbiter global services registered")

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Arbiter from a config entry."""
    rules = entry.options.get(CONF_OBSERVED_ENTITIES, [])

    _LOGGER.info(
        "Setting up Arbiter config entry: entry_id=%s url=%s observed_entity_rules=%d",
        entry.entry_id,
        entry.data.get(CONF_URL),
        len(rules),
    )

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

    _LOGGER.info(
        "Arbiter config entry setup complete: entry_id=%s unsubscribers=%d",
        entry.entry_id,
        len(hass.data[DOMAIN][entry.entry_id]["unsubscribers"]),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Arbiter config entry."""
    _LOGGER.info("Unloading Arbiter config entry: entry_id=%s", entry.entry_id)

    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if data:
        unsubscribers = data.get("unsubscribers", [])
        _LOGGER.info(
            "Removing %d Arbiter listeners for entry_id=%s",
            len(unsubscribers),
            entry.entry_id,
        )

        for unsubscribe in unsubscribers:
            unsubscribe()
    else:
        _LOGGER.warning(
            "No Arbiter runtime data found while unloading entry_id=%s",
            entry.entry_id,
        )

    _LOGGER.info("Arbiter config entry unloaded: entry_id=%s", entry.entry_id)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    _LOGGER.info("Arbiter options changed; reloading entry_id=%s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


def _register_observers(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: ArbiterClient,
) -> None:
    """Register state listeners for configured observed entities."""
    rules = entry.options.get(CONF_OBSERVED_ENTITIES, [])
    data = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.info(
        "Registering Arbiter observers: entry_id=%s rules=%d",
        entry.entry_id,
        len(rules),
    )

    if not rules:
        _LOGGER.warning(
            "No observed entity rules configured for Arbiter entry_id=%s",
            entry.entry_id,
        )

    for rule in rules:
        entity_id = rule[CONF_ENTITY_ID]

        _LOGGER.info(
            "Registering Arbiter observed entity listener: entity_id=%s capability=%s subject=%s severity=%s",
            entity_id,
            rule.get(CONF_CAPABILITY),
            rule.get(CONF_SUBJECT),
            rule.get(CONF_SEVERITY),
        )

        @callback
        def _state_changed(event, rule=rule):
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            event_entity_id = event.data.get("entity_id")

            _LOGGER.info(
                "Arbiter observed entity state event: entity_id=%s old_state=%s new_state=%s",
                event_entity_id,
                old_state.state if old_state is not None else None,
                new_state.state if new_state is not None else None,
            )

            if new_state is None:
                _LOGGER.warning(
                    "Ignoring Arbiter observed entity event with no new_state: entity_id=%s",
                    event_entity_id,
                )
                return

            if old_state is not None and old_state.state == new_state.state:
                _LOGGER.debug(
                    "Ignoring Arbiter observed entity event because state did not change: entity_id=%s state=%s",
                    new_state.entity_id,
                    new_state.state,
                )
                return

            _LOGGER.info(
                "Scheduling Arbiter observed entity pulse: entity_id=%s raw_state=%s",
                new_state.entity_id,
                new_state.state,
            )

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

        _LOGGER.info(
            "Registered Arbiter observed entity listener: entity_id=%s total_listeners=%d",
            entity_id,
            len(data["unsubscribers"]),
        )

        health_entity_id = rule.get(CONF_HEALTH_ENTITY_ID)
        if not health_entity_id:
            _LOGGER.debug(
                "No Arbiter health entity configured for observed entity: entity_id=%s",
                entity_id,
            )
            continue

        _LOGGER.info(
            "Registering Arbiter health entity listener: health_entity_id=%s source_entity_id=%s",
            health_entity_id,
            entity_id,
        )

        @callback
        def _health_state_changed(event, rule=rule):
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            event_entity_id = event.data.get("entity_id")

            _LOGGER.info(
                "Arbiter health entity state event: entity_id=%s old_state=%s new_state=%s",
                event_entity_id,
                old_state.state if old_state is not None else None,
                new_state.state if new_state is not None else None,
            )

            if new_state is None:
                _LOGGER.warning(
                    "Ignoring Arbiter health entity event with no new_state: entity_id=%s",
                    event_entity_id,
                )
                return

            if old_state is not None and old_state.state == new_state.state:
                _LOGGER.debug(
                    "Ignoring Arbiter health entity event because state did not change: entity_id=%s state=%s",
                    new_state.entity_id,
                    new_state.state,
                )
                return

            _LOGGER.info(
                "Scheduling Arbiter health pulse: entity_id=%s raw_state=%s",
                new_state.entity_id,
                new_state.state,
            )

            hass.async_create_task(
                _async_emit_health_state(
                    client=client,
                    rule=rule,
                    old_state=old_state,
                    new_state=new_state,
                )
            )

        unsubscribe = async_track_state_change_event(
            hass,
            [health_entity_id],
            _health_state_changed,
        )
        data["unsubscribers"].append(unsubscribe)

        _LOGGER.info(
            "Registered Arbiter health entity listener: health_entity_id=%s total_listeners=%d",
            health_entity_id,
            len(data["unsubscribers"]),
        )


async def _async_emit_observed_state(
    client: ArbiterClient,
    rule: dict[str, Any],
    old_state,
    new_state,
) -> None:
    """Emit a pulse for an observed entity state change."""
    raw_state = new_state.state
    mapped_state = _map_state(raw_state, rule)

    _LOGGER.info(
        "Preparing Arbiter observed entity pulse: entity_id=%s raw_state=%s mapped_state=%s old_raw_state=%s capability=%s subject=%s",
        new_state.entity_id,
        raw_state,
        mapped_state,
        old_state.state if old_state is not None else None,
        rule.get(CONF_CAPABILITY),
        rule.get(CONF_SUBJECT),
    )

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

    _LOGGER.debug("Sending Arbiter observed entity pulse payload: %s", payload)

    try:
        await client.async_send_pulse(payload)
    except ArbiterClientError:
        _LOGGER.exception(
            "Failed to send observed entity pulse to Arbiter: entity_id=%s capability=%s subject=%s raw_state=%s mapped_state=%s",
            new_state.entity_id,
            rule.get(CONF_CAPABILITY),
            rule.get(CONF_SUBJECT),
            raw_state,
            mapped_state,
        )
        return

    _LOGGER.info(
        "Successfully sent Arbiter observed entity pulse: entity_id=%s capability=%s subject=%s mapped_state=%s",
        new_state.entity_id,
        rule.get(CONF_CAPABILITY),
        rule.get(CONF_SUBJECT),
        mapped_state,
    )


def _map_state(raw_state: str, rule: dict[str, Any]) -> str:
    """Map HA state to Arbiter state."""
    if raw_state == "on" and rule.get(CONF_MAP_ON):
        mapped = rule[CONF_MAP_ON]
        _LOGGER.debug("Mapped Arbiter observed state: raw_state=on mapped_state=%s", mapped)
        return mapped

    if raw_state == "off" and rule.get(CONF_MAP_OFF):
        mapped = rule[CONF_MAP_OFF]
        _LOGGER.debug("Mapped Arbiter observed state: raw_state=off mapped_state=%s", mapped)
        return mapped

    _LOGGER.debug("No Arbiter observed state mapping applied: raw_state=%s", raw_state)
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


async def _async_emit_health_state(
    client: ArbiterClient,
    rule: dict[str, Any],
    old_state,
    new_state,
) -> None:
    """Emit a health pulse for a linked health/status entity."""
    raw_state = new_state.state
    mapped_state = _map_health_state(raw_state, rule)

    _LOGGER.info(
        "Preparing Arbiter health pulse: health_entity_id=%s raw_state=%s mapped_state=%s old_raw_state=%s source_entity_id=%s source_capability=%s source_subject=%s",
        new_state.entity_id,
        raw_state,
        mapped_state,
        old_state.state if old_state is not None else None,
        rule.get(CONF_ENTITY_ID),
        rule.get(CONF_CAPABILITY),
        rule.get(CONF_SUBJECT),
    )

    facts = {
        "state": mapped_state,
        "available": mapped_state,
        "raw_state": raw_state,
        "old_raw_state": old_state.state if old_state is not None else None,
        "entity_id": new_state.entity_id,
        "friendly_name": new_state.attributes.get(ATTR_FRIENDLY_NAME),
        "source": DEFAULT_SOURCE,

        # Link this health signal back to the semantic state it affects.
        "source_entity_id": rule[CONF_ENTITY_ID],
        "source_capability": rule[CONF_CAPABILITY],
        "source_subject": rule[CONF_SUBJECT],
    }

    payload = _build_pulse_payload(
        capability=HEALTH_CAPABILITY,
        subject=_health_subject_for_rule(rule),
        severity=None,
        facts=facts,
        presentation=None,
    )

    _LOGGER.debug("Sending Arbiter health pulse payload: %s", payload)

    try:
        await client.async_send_pulse(payload)
    except ArbiterClientError:
        _LOGGER.exception(
            "Failed to send health pulse to Arbiter: health_entity_id=%s source_entity_id=%s raw_state=%s mapped_state=%s",
            new_state.entity_id,
            rule.get(CONF_ENTITY_ID),
            raw_state,
            mapped_state,
        )
        return

    _LOGGER.info(
        "Successfully sent Arbiter health pulse: health_entity_id=%s source_entity_id=%s mapped_state=%s",
        new_state.entity_id,
        rule.get(CONF_ENTITY_ID),
        mapped_state,
    )


def _map_health_state(raw_state: str, rule: dict[str, Any]) -> str:
    """Map HA health entity state to Arbiter health state."""
    if raw_state == "on" and rule.get(CONF_HEALTH_MAP_ON):
        mapped = rule[CONF_HEALTH_MAP_ON]
        _LOGGER.debug("Mapped Arbiter health state: raw_state=on mapped_state=%s", mapped)
        return mapped

    if raw_state == "off" and rule.get(CONF_HEALTH_MAP_OFF):
        mapped = rule[CONF_HEALTH_MAP_OFF]
        _LOGGER.debug("Mapped Arbiter health state: raw_state=off mapped_state=%s", mapped)
        return mapped

    if raw_state == "unknown" and rule.get(CONF_HEALTH_MAP_UNKNOWN):
        mapped = rule[CONF_HEALTH_MAP_UNKNOWN]
        _LOGGER.debug("Mapped Arbiter health state: raw_state=unknown mapped_state=%s", mapped)
        return mapped

    if raw_state == "unavailable" and rule.get(CONF_HEALTH_MAP_UNAVAILABLE):
        mapped = rule[CONF_HEALTH_MAP_UNAVAILABLE]
        _LOGGER.debug("Mapped Arbiter health state: raw_state=unavailable mapped_state=%s", mapped)
        return mapped

    _LOGGER.debug("No Arbiter health state mapping applied: raw_state=%s", raw_state)
    return raw_state


def _health_subject_for_rule(rule: dict[str, Any]) -> str:
    """Build a stable subject for the linked health state."""
    subject = rule[CONF_SUBJECT]

    if subject.endswith("_lock") or subject.endswith("_sensor"):
        health_subject = subject
    else:
        capability = rule.get(CONF_CAPABILITY, "")

        if capability == "security.lock_changed":
            health_subject = f"{subject}_lock"
        elif capability == "security.entry_open":
            health_subject = f"{subject}_sensor"
        else:
            health_subject = f"{subject}_device"

    _LOGGER.debug(
        "Built Arbiter health subject: source_subject=%s health_subject=%s capability=%s",
        subject,
        health_subject,
        rule.get(CONF_CAPABILITY),
    )

    return health_subject