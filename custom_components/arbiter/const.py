"""Constants for the Arbiter integration."""

DOMAIN = "arbiter"

CONF_URL = "url"
CONF_TOKEN = "token"

CONF_OBSERVED_ENTITIES = "observed_entities"
CONF_ENTITY_ID = "entity_id"
CONF_CAPABILITY = "capability"
CONF_SUBJECT = "subject"
CONF_SEVERITY = "severity"
CONF_MAP_ON = "map_on"
CONF_MAP_OFF = "map_off"

CONF_HEALTH_ENTITY_ID = "health_entity_id"
CONF_HEALTH_MAP_ON = "health_map_on"
CONF_HEALTH_MAP_OFF = "health_map_off"
CONF_HEALTH_MAP_UNKNOWN = "health_map_unknown"
CONF_HEALTH_MAP_UNAVAILABLE = "health_map_unavailable"

HEALTH_CAPABILITY = "device.health_changed"

SERVICE_SEND_PULSE = "send_pulse"

DEFAULT_SOURCE = "home_assistant"
DEFAULT_TIMEOUT_SECONDS = 10
