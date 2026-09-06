package com.factflow.capture

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.factflow.network.VerdictResponse

/**
 * Holds the bubble's current state and the last verdict received.
 * Uses Compose State so that BubbleComposeContent automatically
 * recomposes when these values change.
 */
object RecordingManager {
    enum class State { IDLE, RECORDING, PROCESSING, DONE, ERROR }

    private val _currentState = mutableStateOf(State.IDLE)
    var currentState: State
        get() = _currentState.value
        set(value) {
            android.util.Log.d("RecordingManager", "currentState set to $value")
            _currentState.value = value
        }

    private val _processingStage = mutableStateOf<String?>(null)
    var processingStage: String?
        get() = _processingStage.value
        set(value) {
            android.util.Log.d("RecordingManager", "processingStage set to $value")
            _processingStage.value = value
        }

    private val _lastVerdict = mutableStateOf<VerdictResponse?>(null)
    var lastVerdict: VerdictResponse?
        get() = _lastVerdict.value
        set(value) {
            _lastVerdict.value = value
        }

    private val _lastError = mutableStateOf<String?>(null)
    var lastError: String?
        get() = _lastError.value
        set(value) {
            _lastError.value = value
        }

    fun reset() {
        currentState = State.IDLE
        processingStage = null
        lastVerdict = null
        lastError = null
    }
}
