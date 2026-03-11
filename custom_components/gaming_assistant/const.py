"""Constants for the Gaming Assistant integration."""

DOMAIN = "gaming_assistant"

CONF_OLLAMA_HOST = "ollama_host"
CONF_MODEL = "model"
CONF_INTERVAL = "interval"

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5vl"
DEFAULT_INTERVAL = 10

MQTT_TIP_TOPIC = "gaming_assistant/tip"
MQTT_MODE_TOPIC = "gaming_assistant/gaming_mode"
MQTT_STATUS_TOPIC = "gaming_assistant/status"

ATTR_LAST_TIP = "last_tip"
ATTR_GAMING_MODE = "gaming_mode"
