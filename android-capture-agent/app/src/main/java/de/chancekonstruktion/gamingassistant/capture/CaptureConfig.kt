package de.chancekonstruktion.gamingassistant.capture

data class CaptureConfig(
    val brokerHost: String = "",
    val brokerPort: Int = 1883,
    val username: String = "",
    val password: String = "",
    val clientId: String = "android-client",
    val intervalSeconds: Int = 5,
    val jpegQuality: Int = 70,
    val gameHint: String = "",
    /** Show tips from Home Assistant on top of the game (GA-112). */
    val showTipOverlay: Boolean = false,
)
