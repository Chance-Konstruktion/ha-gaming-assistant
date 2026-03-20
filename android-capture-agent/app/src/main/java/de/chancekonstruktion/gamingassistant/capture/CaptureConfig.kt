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
)
