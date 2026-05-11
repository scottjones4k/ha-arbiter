# Arbiter Home Assistant Integration

First-cut custom integration for sending Home Assistant state changes to Arbiter.

## Features

- UI config flow for Arbiter URL and bearer token
- `arbiter.send_pulse` action/service
- UI options flow for observed entities
- Observed state changes are POSTed to Arbiter as pulses

## Install via HACS custom repository

1. Push this repository to GitHub.
2. In HACS, add it as a custom repository.
3. Category: Integration.
4. Install, restart Home Assistant.
5. Add integration: Settings → Devices & services → Add Integration → Arbiter.

## Observed entity rule

Each rule has:

- Entity ID
- Capability
- Subject
- Optional severity
- `on` mapped state
- `off` mapped state

For any state not in the explicit map, the raw HA state is used as the Arbiter `facts.state`.

## Sent payload example

```json
{
  "capability": "security.lock_changed",
  "subject": "front_door",
  "severity": "info",
  "facts": {
    "state": "unlocked",
    "raw_state": "on",
    "old_raw_state": "off",
    "entity_id": "input_boolean.front_door_locked",
    "friendly_name": "Front Door Locked",
    "source": "home_assistant"
  }
}
```
