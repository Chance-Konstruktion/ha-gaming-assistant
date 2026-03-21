package de.chancekonstruktion.gamingassistant.capture

data class CaptureStatus(
    val serviceRunning: Boolean = false,
    val mqttConnected: Boolean = false,
    val sentFrames: Int = 0,
    val lastError: String = "",
)
