"""Constants for the Gaming Assistant integration."""

DOMAIN = "gaming_assistant"

CONF_OLLAMA_HOST = "ollama_host"
CONF_MODEL = "model"
CONF_INTERVAL = "interval"
CONF_TIMEOUT = "analysis_timeout"

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5vl"
DEFAULT_INTERVAL = 10
DEFAULT_TIMEOUT = 60

# Legacy MQTT Topics (v0.2/v0.3 compatibility)
MQTT_TIP_TOPIC = "gaming_assistant/tip"
MQTT_MODE_TOPIC = "gaming_assistant/gaming_mode"
MQTT_STATUS_TOPIC = "gaming_assistant/status"

# New MQTT Topics (v0.4 Thin Client)
MQTT_IMAGE_TOPIC = "gaming_assistant/+/image"  # + = client_id wildcard
MQTT_META_TOPIC = "gaming_assistant/+/meta"

# Spoiler Levels
SPOILER_CATEGORIES = [
    "story", "items", "enemies", "bosses", "locations", "lore", "mechanics",
]
SPOILER_LEVELS = ["none", "low", "medium", "high"]

# History
DEFAULT_HISTORY_SIZE = 50
HISTORY_CONTEXT_SIZE = 5  # Last N tips included in prompt

# Config Keys
CONF_SPOILER_SETTINGS = "spoiler_settings"
CONF_DEFAULT_SPOILER = "default_spoiler_level"
DEFAULT_SPOILER_LEVEL = "medium"

# Attributes
ATTR_LAST_TIP = "last_tip"
ATTR_GAMING_MODE = "gaming_mode"

# Image Processing
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB hard limit for base64-decoded images
IMAGE_DEDUP_WINDOW_SECONDS = 60
OLLAMA_TIMEOUT = 60
OLLAMA_RETRY_DELAY = 5
OLLAMA_NUM_PREDICT = 120
