package de.chancekonstruktion.gamingassistant.capture

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

object CaptureStatusBus {
    private val _status = MutableStateFlow(CaptureStatus())
    val status: StateFlow<CaptureStatus> = _status.asStateFlow()

    fun update(transform: (CaptureStatus) -> CaptureStatus) {
        _status.value = transform(_status.value)
    }

    fun reset() {
        _status.value = CaptureStatus()
    }
}
