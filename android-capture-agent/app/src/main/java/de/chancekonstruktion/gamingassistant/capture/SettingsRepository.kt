package de.chancekonstruktion.gamingassistant.capture

import android.content.Context
import android.os.Build

class SettingsRepository(context: Context) {
    private val prefs = context.getSharedPreferences("capture_settings", Context.MODE_PRIVATE)

    fun load(): CaptureConfig {
        val defaultId = "android-${Build.MODEL}".replace(" ", "-").lowercase()
        return CaptureConfig(
            brokerHost = prefs.getString("brokerHost", "") ?: "",
            brokerPort = prefs.getInt("brokerPort", 1883),
            username = prefs.getString("username", "") ?: "",
            password = prefs.getString("password", "") ?: "",
            clientId = prefs.getString("clientId", defaultId) ?: defaultId,
            intervalSeconds = prefs.getInt("intervalSeconds", 5),
            jpegQuality = prefs.getInt("jpegQuality", 70),
            gameHint = prefs.getString("gameHint", "") ?: "",
        )
    }

    fun save(config: CaptureConfig) {
        prefs.edit()
            .putString("brokerHost", config.brokerHost)
            .putInt("brokerPort", config.brokerPort)
            .putString("username", config.username)
            .putString("password", config.password)
            .putString("clientId", config.clientId)
            .putInt("intervalSeconds", config.intervalSeconds)
            .putInt("jpegQuality", config.jpegQuality)
            .putString("gameHint", config.gameHint)
            .apply()
    }
}
