"""Constants for the Gaming Assistant integration."""

DOMAIN = "gaming_assistant"

CONF_OLLAMA_HOST = "ollama_host"
CONF_MODEL = "model"
CONF_LLM_BACKEND = "llm_backend"
CONF_LLM_API_KEY = "llm_api_key"
CONF_LLM_ALLOW_IMAGES = "llm_allow_images"
DEFAULT_LLM_BACKEND = "ollama"
CONF_INTERVAL = "interval"
CONF_TIMEOUT = "analysis_timeout"
CONF_CAMERA_ENTITY = "camera_entity"

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
MQTT_WORKER_REGISTER_TOPIC = "gaming_assistant/+/register"
MQTT_DETECTIONS_TOPIC = "gaming_assistant/+/detections"
MQTT_YOLO_COMMAND_TOPIC = "gaming_assistant/yolo/command"
# Per-client status topic. Carries BOTH plain-text capture-agent presence
# ("online"/"offline" via LWT) and JSON YOLO-worker status on the same
# 3-segment pattern, so the handler must tolerate both payload shapes.
MQTT_YOLO_STATUS_TOPIC = "gaming_assistant/+/status"

# Agent Mode action topic (publish): {client_id} is the target capture client.
MQTT_ACTION_TOPIC = "gaming_assistant/{client_id}/action"

# Spoiler Levels
SPOILER_CATEGORIES = [
    "story", "items", "enemies", "bosses", "locations", "lore", "mechanics",
]
SPOILER_LEVELS = ["none", "low", "medium", "high"]

# History
DEFAULT_HISTORY_SIZE = 50
HISTORY_CONTEXT_SIZE = 5  # Last N tips included in prompt

# Config Keys
CONF_DEFAULT_SPOILER = "default_spoiler_level"
DEFAULT_SPOILER_LEVEL = "medium"

# Assistant Modes
ASSISTANT_MODES = ["coach", "coplay", "opponent", "analyst"]
DEFAULT_ASSISTANT_MODE = "coach"

# Source Types (how the camera sees the game)
SOURCE_TYPES = ["auto", "console", "tabletop"]
DEFAULT_SOURCE_TYPE = "auto"

# Agent Mode / Player 2 — opt-in autonomous controller actions.
# Runtime-only by design: always starts OFF and resets to OFF on restart,
# so the AI never controls inputs unless deliberately re-enabled.
DEFAULT_AGENT_MODE = False
# Valid Xbox buttons the AI may use (matches PromptBuilder.ACTION_SCHEMA).
# An empty whitelist means "all of these".
AGENT_VALID_BUTTONS = [
    "A", "B", "X", "Y", "LB", "RB", "LT", "RT",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "START", "BACK",
]

# TTS / Announce
CONF_TTS_ENTITY = "tts_entity"
CONF_TTS_TARGET = "tts_target"
CONF_AUTO_ANNOUNCE = "auto_announce"
DEFAULT_AUTO_ANNOUNCE = False

# Event fired on every new tip (for automations)
EVENT_NEW_TIP = "gaming_assistant_new_tip"

# Event fired when a gaming session ends
EVENT_SESSION_ENDED = "gaming_assistant_session_ended"

# Session Summary
CONF_AUTO_SUMMARY = "auto_summary"
DEFAULT_AUTO_SUMMARY = False
SESSION_END_DELAY = 300  # 5 minutes of inactivity before session ends

# Image Processing
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB hard limit for base64-decoded images
IMAGE_DEDUP_WINDOW_SECONDS = 60
IMAGE_MAX_DIMENSION = 1280  # Max width/height before sending to LLM
IMAGE_DOWNSCALE_QUALITY = 85  # JPEG quality for downscaled images
OLLAMA_TIMEOUT = 60
OLLAMA_NUM_PREDICT = 200
