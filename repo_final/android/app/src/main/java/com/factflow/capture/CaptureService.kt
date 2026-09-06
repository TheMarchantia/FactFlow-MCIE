package com.factflow.capture

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaRecorder
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import com.factflow.MainActivity
import com.factflow.R
import java.io.File

/**
 * Owns the app's MediaProjection session for the lifetime of one "bubble
 * session" (Sections 4.2/4.4). The user grants screen-recording consent
 * ONCE, in MainActivity, when they tap "Enable verification bubble". That
 * single MediaProjection instance is kept alive here and reused to create
 * and release a fresh VirtualDisplay + MediaRecorder pair for EACH two-tap
 * recording; the projection itself is only stopped when the whole bubble
 * session ends. This deliberately avoids re-prompting the system's screen
 * capture consent dialog before every single clip, which would otherwise
 * interrupt the "tap bubble, keep scrolling" flow the architecture doc
 * describes.
 *
 * NOTE on audio (an intentional, documented scope decision, not a silently
 * dropped feature): this records the device MICROPHONE
 * (MediaRecorder.AudioSource.MIC), not isolated in-app playback audio.
 * True in-app-only audio capture per Section 4.3
 * (AudioPlaybackCaptureConfiguration) requires building a raw AudioRecord +
 * MediaCodec AAC encoder + MediaMuxer pipeline instead of MediaRecorder --
 * meaningfully more code, and a separate follow-up task. For a phone
 * recording a reel that's playing through its own speaker, the microphone
 * captures the same speech Whisper.cpp needs downstream, so this is a
 * reasonable interim substitute rather than a missing feature.
 */
class CaptureService : Service() {

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var mediaRecorder: MediaRecorder? = null
    private var outputFile: File? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            // The system can revoke the projection out from under us (e.g. the
            // user taps "Stop" on the system's screen-recording notification).
            Log.w(TAG, "MediaProjection stopped by the system.")
            releaseAllCaptureResources()
            mediaProjection = null
            Callbacks.onSessionFailed?.invoke("Screen recording was stopped from the system notification.")
            stopSelf()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_INIT -> handleInit(intent)
            ACTION_START_RECORDING -> handleStartRecording()
            ACTION_STOP_RECORDING -> handleStopRecording()
            ACTION_END_SESSION -> handleEndSession()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        handleEndSession()
    }

    // ---------- Session lifecycle (once per "Enable verification bubble") ----------

    private fun handleInit(intent: Intent) {
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, android.app.Activity.RESULT_CANCELED)
        val data = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION") intent.getParcelableExtra(EXTRA_RESULT_DATA)
        }
        if (data == null || resultCode != android.app.Activity.RESULT_OK) {
            Log.e(TAG, "Missing/invalid screen-capture consent; cannot start capture session.")
            Callbacks.onSessionFailed?.invoke("Screen recording permission was not granted.")
            stopSelf()
            return
        }

        // Must call startForeground() with a "mediaProjection" typed service
        // BEFORE requesting the MediaProjection instance -- required since
        // Android 10, strictly enforced since Android 14.
        startForegroundWithNotification()

        val manager = getSystemService(MediaProjectionManager::class.java)
        try {
            val projection = manager.getMediaProjection(resultCode, data)
            projection.registerCallback(projectionCallback, mainHandler)
            mediaProjection = projection
            Callbacks.onSessionReady?.invoke()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to obtain MediaProjection", e)
            Callbacks.onSessionFailed?.invoke("Could not start screen recording: ${e.message}")
            stopSelf()
        }
    }

    private fun handleEndSession() {
        releaseAllCaptureResources()
        mediaProjection?.let { projection ->
            runCatching { projection.unregisterCallback(projectionCallback) }
            runCatching { projection.stop() }
        }
        mediaProjection = null
    }

    // ---------- Per-clip recording (one cycle per two-tap capture) ----------

    private fun handleStartRecording() {
        val projection = mediaProjection
        if (projection == null) {
            Callbacks.onRecordingFailed?.invoke("Screen capture session isn't ready yet -- try again in a moment.")
            return
        }
        val metrics = DisplayMetrics()
        val wm = getSystemService(WindowManager::class.java)
        @Suppress("DEPRECATION") wm.defaultDisplay.getRealMetrics(metrics)
        val (width, height) = clampToEncoderSafeSize(metrics.widthPixels, metrics.heightPixels)
        val dpi = metrics.densityDpi

        val file = File(cacheDir, "factflow_capture_${System.currentTimeMillis()}.mp4")
        outputFile = file

        // Try video+audio first; if the device/emulator can't prepare that
        // combination (no usable mic input is a common cause of a generic
        // "prepare failed" here), fall back to video-only rather than
        // failing the whole recording. The backend doesn't consume audio
        // yet anyway (Whisper.cpp isn't wired up -- transcript is always
        // [] today), so this costs nothing functionally in the meantime.
        val recorder = buildAndPrepareRecorder(file, width, height, includeAudio = true)
            ?: buildAndPrepareRecorder(file, width, height, includeAudio = false)

        if (recorder == null) {
            outputFile?.delete()
            outputFile = null
            Callbacks.onRecordingFailed?.invoke(
                "Could not start recording: the device's encoder rejected size ${width}x$height.",
            )
            return
        }

        try {
            val display = virtualDisplay
            if (display == null) {
                // First clip of this session: create the VirtualDisplay bound
                // to this MediaProjection. It is deliberately NOT released
                // after this clip -- see releaseRecorderOnly() below -- and
                // is reused for every subsequent clip in the session.
                virtualDisplay = projection.createVirtualDisplay(
                    "FactFlowCapture",
                    width, height, dpi,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    recorder.surface, null, mainHandler,
                )
            } else {
                // Subsequent clip: redirect the SAME VirtualDisplay to this
                // clip's new MediaRecorder Surface. On Android 14+, releasing
                // and recreating the VirtualDisplay per clip invalidates the
                // whole MediaProjection grant (the system stops it as soon as
                // the first VirtualDisplay is released), which is exactly
                // what caused "Don't re-use the resultData..." on the 2nd
                // recording -- so the VirtualDisplay itself must stay alive
                // for the whole session and only its target Surface changes.
                display.setSurface(recorder.surface)
            }

            recorder.start()
            mediaRecorder = recorder
            Callbacks.onRecordingStarted?.invoke()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start recording", e)
            releaseRecorderOnly()
            outputFile?.delete()
            outputFile = null
            Callbacks.onRecordingFailed?.invoke("Could not start recording: ${e.message}")
        }
    }

    /**
     * Some devices' hardware H.264 encoders can't handle MediaRecorder
     * video capture at the device's full native panel resolution (common
     * on high-resolution phones), which makes prepare() fail with a
     * generic native error. Cap the longer edge at a broadly-supported
     * size, preserving aspect ratio, and keep both dimensions even (most
     * encoders require this).
     */
    private fun clampToEncoderSafeSize(rawWidth: Int, rawHeight: Int, maxDimension: Int = 1920): Pair<Int, Int> {
        val longEdge = maxOf(rawWidth, rawHeight)
        val scale = if (longEdge > maxDimension) maxDimension.toFloat() / longEdge else 1f
        val width = ((rawWidth * scale).toInt() / 2) * 2
        val height = ((rawHeight * scale).toInt() / 2) * 2
        return width.coerceAtLeast(2) to height.coerceAtLeast(2)
    }

    /**
     * Builds a MediaRecorder configured for screen (+ optionally mic) capture
     * and calls prepare(). Returns null (after cleaning up the failed
     * instance) instead of throwing, so callers can try a fallback
     * configuration -- see the includeAudio=false retry in
     * handleStartRecording().
     */
    private fun buildAndPrepareRecorder(file: File, width: Int, height: Int, includeAudio: Boolean): MediaRecorder? {
        val recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(this)
        } else {
            @Suppress("DEPRECATION") MediaRecorder()
        }
        return try {
            // Order matters: sources before setOutputFormat; encoders/sizes
            // after setOutputFormat but before prepare().
            recorder.setVideoSource(MediaRecorder.VideoSource.SURFACE)
            if (includeAudio) recorder.setAudioSource(MediaRecorder.AudioSource.MIC)
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            recorder.setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            if (includeAudio) recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            recorder.setVideoSize(width, height)
            recorder.setVideoFrameRate(30)
            recorder.setVideoEncodingBitRate(6_000_000)
            if (includeAudio) {
                recorder.setAudioEncodingBitRate(128_000)
                recorder.setAudioSamplingRate(44_100)
            }
            recorder.setOutputFile(file.absolutePath)
            recorder.prepare()
            recorder
        } catch (e: Exception) {
            Log.w(TAG, "MediaRecorder prepare() failed (includeAudio=$includeAudio, size=${width}x$height)", e)
            runCatching { recorder.reset() }
            runCatching { recorder.release() }
            null
        }
    }

    private fun handleStopRecording() {
        val recorder = mediaRecorder
        val file = outputFile
        if (recorder == null || file == null) {
            Callbacks.onRecordingFailed?.invoke("No active recording to stop.")
            return
        }
        try {
            // MediaRecorder.stop() throws RuntimeException if called too soon
            // after start() (too few frames written) -- this is a documented
            // MediaRecorder quirk, not an edge case to ignore.
            recorder.stop()
            releaseRecorderOnly()
            if (file.exists() && file.length() > 0) {
                Callbacks.onRecordingFinished?.invoke(file)
            } else {
                file.delete()
                Callbacks.onRecordingFailed?.invoke("Recording produced an empty file.")
            }
        } catch (e: RuntimeException) {
            Log.e(TAG, "MediaRecorder.stop() failed (recording was likely too short)", e)
            releaseRecorderOnly()
            file.delete()
            Callbacks.onRecordingFailed?.invoke("Recording was too short -- hold it for at least a second.")
        } finally {
            outputFile = null
        }
    }

    /** Releases only the per-clip MediaRecorder; the session's VirtualDisplay
     * (and the MediaProjection grant it keeps alive) is left untouched --
     * see the class doc and handleStartRecording() for why. */
    private fun releaseRecorderOnly() {
        virtualDisplay?.setSurface(null)
        runCatching { mediaRecorder?.reset() }
        runCatching { mediaRecorder?.release() }
        mediaRecorder = null
    }

    /** Releases the recorder AND the session's VirtualDisplay -- only called
     * when the whole bubble session is ending (handleEndSession(), or the
     * system revoking the projection out from under us). */
    private fun releaseAllCaptureResources() {
        releaseRecorderOnly()
        runCatching { virtualDisplay?.release() }
        virtualDisplay = null
    }

    private fun startForegroundWithNotification() {
        val channelId = "factflow_capture_channel"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId, "FactFlow Screen Recording", NotificationManager.IMPORTANCE_LOW,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
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
            .setContentTitle("FactFlow can record your screen")
            .setContentText("Tap the bubble to start or stop verifying a clip.")
            .setSmallIcon(R.drawable.ic_bubble)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
    }

    /**
     * In-process callback registry. CaptureService and BubbleService always
     * run in the same app process, so a simple set of nullable lambdas is
     * sufficient here and avoids the overhead of a bound-service interface
     * for what is a single, known consumer (BubbleService).
     */
    object Callbacks {
        var onSessionReady: (() -> Unit)? = null
        var onSessionFailed: ((String) -> Unit)? = null
        var onRecordingStarted: (() -> Unit)? = null
        var onRecordingFinished: ((File) -> Unit)? = null
        var onRecordingFailed: ((String) -> Unit)? = null
    }

    companion object {
        private const val TAG = "CaptureService"
        private const val NOTIFICATION_ID = 1002

        private const val ACTION_INIT = "com.factflow.capture.INIT"
        private const val ACTION_START_RECORDING = "com.factflow.capture.START_RECORDING"
        private const val ACTION_STOP_RECORDING = "com.factflow.capture.STOP_RECORDING"
        private const val ACTION_END_SESSION = "com.factflow.capture.END_SESSION"
        private const val EXTRA_RESULT_CODE = "result_code"
        private const val EXTRA_RESULT_DATA = "result_data"

        /** Called once, right after MainActivity receives screen-capture consent. */
        fun initSession(context: Context, resultCode: Int, data: Intent) {
            val intent = Intent(context, CaptureService::class.java).apply {
                action = ACTION_INIT
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, data)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        /** Called on the bubble's first tap of a two-tap cycle. */
        fun startRecording(context: Context) {
            context.startService(Intent(context, CaptureService::class.java).apply { action = ACTION_START_RECORDING })
        }

        /** Called on the bubble's second tap of a two-tap cycle. */
        fun stopRecording(context: Context) {
            context.startService(Intent(context, CaptureService::class.java).apply { action = ACTION_STOP_RECORDING })
        }

        /** Called when the whole bubble session ends ("Hide" tapped). */
        fun endSession(context: Context) {
            context.startService(Intent(context, CaptureService::class.java).apply { action = ACTION_END_SESSION })
        }
    }
}