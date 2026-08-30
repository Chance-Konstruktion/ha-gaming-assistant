package de.chancekonstruktion.gamingassistant.capture

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val repository = SettingsRepository(app)

    private val _config = MutableStateFlow(repository.load())
    val config: StateFlow<CaptureConfig> = _config.asStateFlow()

    val status: StateFlow<CaptureStatus> = CaptureStatusBus.status.stateIn(
        viewModelScope,
        started = kotlinx.coroutines.flow.SharingStarted.WhileSubscribed(5000),
        initialValue = CaptureStatus(),
    )

    fun updateConfig(update: (CaptureConfig) -> CaptureConfig) {
        _config.update(update)
        viewModelScope.launch {
            repository.save(_config.value)
        }
    }
}
