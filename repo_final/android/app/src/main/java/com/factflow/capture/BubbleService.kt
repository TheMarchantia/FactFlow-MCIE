package com.factflow.capture

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.util.Log
import android.view.Choreographer
import android.view.Gravity
import android.view.MotionEvent
import android.view.WindowManager
import android.os.SystemClock
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Recomposer
import androidx.compose.ui.platform.compositionContext
import androidx.core.app.NotificationCompat
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.ViewCompositionStrategy
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.lifecycle.setViewTreeViewModelStoreOwner
import androidx.savedstate.SavedStateRegistry
import androidx.savedstate.SavedStateRegistryController
import androidx.savedstate.SavedStateRegistryOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner
import com.factflow.MainActivity
import com.factflow.R
import com.factflow.network.PipelineResult
import com.factflow.network.UploadManager
import com.factflow.ui.bubble.BubbleComposeContent
import com.factflow.ui.bubble.FullReportPopup
import com.factflow.ui.bubble.VerdictPopup
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.io.File
import kotlin.math.abs

/**
 * The floating bubble overlay + foreground service.
 */
class BubbleService : Service(), LifecycleOwner, ViewModelStoreOwner, SavedStateRegistryOwner {

    private lateinit var windowManager: WindowManager
    private var composeView: ComposeView? = null
    private var popup: VerdictPopup? = null
    private var fullReportPopup: FullReportPopup? = null
    private var serviceJob: Job = SupervisorJob()
    private lateinit var scope: CoroutineScope
    private var choreographer: Choreographer? = null
    private var frameCallback: Choreographer.FrameCallback? = null
    private var lastVerdictTapAt = 0L

    private val lifecycleRegistry = LifecycleRegistry(this)
    override val lifecycle: Lifecycle get() = lifecycleRegistry

    private val _viewModelStore = ViewModelStore()
    override val viewModelStore: ViewModelStore get() = _viewModelStore

    private val savedStateRegistryController = SavedStateRegistryController.create(this)
    override val savedStateRegistry: SavedStateRegistry get() = savedStateRegistryController.savedStateRegistry

    override fun onCreate() {
        super.onCreate()
        savedStateRegistryController.performRestore(null)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_CREATE)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_START)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_RESUME)
        
        scope = CoroutineScope(Dispatchers.Main + serviceJob)
        startForegroundWithNotification()
        addBubbleOverlay()
        registerCaptureCallbacks()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        super.onDestroy()
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_PAUSE)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_STOP)
        lifecycleRegistry.handleLifecycleEvent(Lifecycle.Event.ON_DESTROY)
        frameCallback?.let { choreographer?.removeFrameCallback(it) }
        frameCallback = null
        choreographer = null
        scope.cancel()
        popup?.dismiss()
        fullReportPopup?.dismiss()
        composeView?.let { runCatching { windowManager.removeView(it) } }
        composeView = null
        clearCaptureCallbacks()
        CaptureService.endSession(this)
        RecordingManager.reset()
    }

    // ---------- CaptureService callbacks ----------

    private fun registerCaptureCallbacks() {
        CaptureService.Callbacks.onRecordingFinished = { file ->
            scope.launch { runUploadPipeline(file) }
        }
        CaptureService.Callbacks.onRecordingFailed = { message ->
            RecordingManager.currentState = RecordingManager.State.ERROR
            RecordingManager.lastError = message
        }
        CaptureService.Callbacks.onSessionFailed = { message ->
            RecordingManager.currentState = RecordingManager.State.ERROR
            RecordingManager.lastError = message
        }
    }

    private fun clearCaptureCallbacks() {
        CaptureService.Callbacks.onRecordingFinished = null
        CaptureService.Callbacks.onRecordingFailed = null
        CaptureService.Callbacks.onSessionFailed = null
        CaptureService.Callbacks.onSessionReady = null
        CaptureService.Callbacks.onRecordingStarted = null
    }

    // ---------- Notification / foreground ----------

    private fun startForegroundWithNotification() {
        val channelId = "factflow_bubble_channel"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId, "FactFlow Bubble", NotificationManager.IMPORTANCE_MIN
            )
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
        val tapIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingFlags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M)
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        else
            PendingIntent.FLAG_UPDATE_CURRENT
        val pendingIntent = PendingIntent.getActivity(this, 0, tapIntent, pendingFlags)

        val notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("FactFlow is running")
            .setContentText("Tap the bubble to verify a claim.")
            .setSmallIcon(R.drawable.ic_bubble)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
    }

    // ---------- Overlay bubble ----------

    private fun addBubbleOverlay() {
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        
        // Manual recomposer for Service environment
        val frameClock = BroadcastFrameClock()
        val recomposer = Recomposer(Dispatchers.Main + frameClock)
        scope.launch(Dispatchers.Main + frameClock) {
            recomposer.runRecomposeAndApplyChanges()
        }
        
        // Drive the frame clock
        val choreo = Choreographer.getInstance()
        val callback = object : Choreographer.FrameCallback {
            override fun doFrame(frameTimeNanos: Long) {
                frameClock.sendFrame(frameTimeNanos)
                choreo.postFrameCallback(this)
            }
        }
        choreographer = choreo
        frameCallback = callback
        choreo.postFrameCallback(callback)

        val view = ComposeView(this).apply {
            setViewTreeLifecycleOwner(this@BubbleService)
            setViewTreeViewModelStoreOwner(this@BubbleService)
            setViewTreeSavedStateRegistryOwner(this@BubbleService)
            
            compositionContext = recomposer
            
            setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnLifecycleDestroyed(this@BubbleService))

            setContent {
                BubbleComposeContent()
            }

            // Without this, the overlay window's default background shows
            // through as a faint square behind the circular bubble.
            setBackgroundColor(android.graphics.Color.TRANSPARENT)
        }
        composeView = view

        val overlayType =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else
                @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            overlayType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 0
            y = 300
        }

        var initialX = 0
        var initialY = 0
        var initialTouchX = 0f
        var initialTouchY = 0f
        var moved = false

        view.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = params.x
                    initialY = params.y
                    initialTouchX = event.rawX
                    initialTouchY = event.rawY
                    moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - initialTouchX)
                    val dy = (event.rawY - initialTouchY)
                    if (abs(dx) > TOUCH_SLOP_PX || abs(dy) > TOUCH_SLOP_PX) {
                        moved = true
                        params.x = initialX + dx.toInt()
                        params.y = initialY + dy.toInt()
                        runCatching { windowManager.updateViewLayout(view, params) }
                    }
                }
                MotionEvent.ACTION_UP -> if (!moved) {
                    if (RecordingManager.currentState == RecordingManager.State.DONE) {
                        val now = SystemClock.uptimeMillis()
                        if (now - lastVerdictTapAt <= DOUBLE_TAP_WINDOW_MS) {
                            lastVerdictTapAt = 0L
                            showVerdictPopup()
                        } else {
                            lastVerdictTapAt = now
                        }
                    } else {
                        onBubbleTapped()
                    }
                }
            }
            true
        }

        windowManager.addView(view, params)
    }

    // ---------- Tap state machine ----------

    private fun onBubbleTapped() {
        when (RecordingManager.currentState) {
            RecordingManager.State.IDLE -> {
                RecordingManager.currentState = RecordingManager.State.RECORDING
                Log.i(TAG, "Recording started.")
                CaptureService.startRecording(this)
            }
            RecordingManager.State.RECORDING -> {
                RecordingManager.currentState = RecordingManager.State.PROCESSING
                Log.i(TAG, "Recording stopped -- finalizing clip.")
                CaptureService.stopRecording(this)
                // The upload pipeline continues once CaptureService reports
                // the finished file via Callbacks.onRecordingFinished.
            }
            RecordingManager.State.PROCESSING -> {
                // Ignore taps while a request is in flight.
            }
            RecordingManager.State.DONE -> {
                // A completed result opens only on double-tap (Section 4.7).
            }
            RecordingManager.State.ERROR -> {
                RecordingManager.reset()
            }
        }
    }

    private fun showVerdictPopup() {
        if (RecordingManager.currentState != RecordingManager.State.DONE) return
        RecordingManager.lastVerdict?.let { verdict ->
            if (popup?.isShowing() != true) {
                popup = VerdictPopup(this).also {
                    it.show(
                        verdict = verdict,
                        onClose = {
                            // Closing prepares the bubble for the next two-tap capture.
                            RecordingManager.reset()
                        },
                        onViewFullDetails = {
                            popup?.dismiss()
                            popup = null
                            showFullReportPopup(verdict)
                        },
                    )
                }
            }
        }
    }

    private fun showFullReportPopup(verdict: com.factflow.network.VerdictResponse) {
        if (fullReportPopup?.isShowing() == true) return
        fullReportPopup = FullReportPopup(this).also {
            it.show(verdict) {
                fullReportPopup?.dismiss()
                fullReportPopup = null
                // Returning from the full report goes back to the bubble in
                // its coloured state, not straight to a reset -- the result
                // can still be revisited (Section 4.7).
            }
        }
    }

    private suspend fun runUploadPipeline(clipFile: File) {
        try {
            when (val result = UploadManager.uploadAndAwaitVerdict(clipFile) { stage ->
                RecordingManager.processingStage = stage
            }) {
                is PipelineResult.Success -> {
                    RecordingManager.lastVerdict = result.verdict
                    RecordingManager.currentState = RecordingManager.State.DONE
                    RecordingManager.processingStage = null
                    Log.i(TAG, "Verdict received: ${result.verdict.claims.firstOrNull()?.verdict}")
                }
                is PipelineResult.Failure -> {
                    RecordingManager.currentState = RecordingManager.State.ERROR
                    RecordingManager.processingStage = null
                    RecordingManager.lastError = result.message
                    Log.e(TAG, "Pipeline failed: ${result.message}")
                }
            }
        } finally {
            if (clipFile.exists()) {
                clipFile.delete()
                Log.d(TAG, "Temporary clip file deleted: ${clipFile.name}")
            }
        }
    }

    companion object {
        private const val TAG = "BubbleService"
        private const val NOTIFICATION_ID = 1001
        private const val TOUCH_SLOP_PX = 12
        private const val DOUBLE_TAP_WINDOW_MS = 320L
    }
}
