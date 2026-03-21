package de.chancekonstruktion.gamingassistant.capture

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.util.DisplayMetrics
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.eclipse.paho.client.mqttv3.IMqttActionListener
import org.eclipse.paho.client.mqttv3.IMqttToken
import org.eclipse.paho.client.mqttv3.MqttAsyncClient
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence
import org.json.JSONObject
import java.io.ByteArrayOutputStream

class CaptureService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var captureJob: Job? = null

    private var mqttClient: MqttAsyncClient? = null
    private var config: CaptureConfig = CaptureConfig()
    private var sentFrames = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startCapture(intent)
            ACTION_STOP -> stopCaptureAndSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        stopCapture()
        serviceScope.cancel()
        super.onDestroy()
    }

    private fun startCapture(intent: Intent) {
        startForeground(NOTIF_ID, buildNotification("Starting…"))

        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, -1)
        val resultData = intent.getParcelableExtraCompat<Intent>(EXTRA_RESULT_DATA)
        if (resultCode != RESULT_OK || resultData == null) {
            pushError("Missing screen capture permission token")
            stopCaptureAndSelf()
            return
        }

        config = CaptureConfig(
            brokerHost = intent.getStringExtra(EXTRA_BROKER_HOST).orEmpty(),
            brokerPort = intent.getIntExtra(EXTRA_BROKER_PORT, 1883),
            username = intent.getStringExtra(EXTRA_USERNAME).orEmpty(),
            password = intent.getStringExtra(EXTRA_PASSWORD).orEmpty(),
            clientId = intent.getStringExtra(EXTRA_CLIENT_ID).orEmpty(),
            intervalSeconds = intent.getIntExtra(EXTRA_INTERVAL_SECONDS, 5),
            jpegQuality = intent.getIntExtra(EXTRA_JPEG_QUALITY, 70),
            gameHint = intent.getStringExtra(EXTRA_GAME_HINT).orEmpty(),
        )

        if (config.brokerHost.isBlank() || config.clientId.isBlank()) {
            pushError("Broker host and clientId are required")
            stopCaptureAndSelf()
            return
        }

        setupProjection(resultCode, resultData)
        setupMqtt()
        startCaptureLoop()

        CaptureStatusBus.update { it.copy(serviceRunning = true, lastError = "") }
        updateNotification("Screenshots senden an ${config.brokerHost}")
    }

    private fun setupProjection(resultCode: Int, resultData: Intent) {
        val projectionManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjection = projectionManager.getMediaProjection(resultCode, resultData)

        val metrics: DisplayMetrics = resources.displayMetrics

        val srcWidth = metrics.widthPixels.coerceAtLeast(1)
        val srcHeight = metrics.heightPixels.coerceAtLeast(1)
        val scale = (1280f / srcWidth).coerceAtMost(1f)
        val width = (srcWidth * scale).toInt().coerceAtLeast(1)
        val height = (srcHeight * scale).toInt().coerceAtLeast(1)
        val density = metrics.densityDpi.coerceAtLeast(1)

        imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        virtualDisplay = mediaProjection?.createVirtualDisplay(
            "ga-capture",
            width,
            height,
            density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader?.surface,
            null,
            null,
        )
    }

    private fun setupMqtt() {
        val serverUri = "tcp://${config.brokerHost}:${config.brokerPort}"
        runCatching { mqttClient?.disconnectForcibly(0, 0) }
        mqttClient?.close()

        mqttClient = MqttAsyncClient(serverUri, config.clientId, MemoryPersistence())
        val options = MqttConnectOptions().apply {
            isAutomaticReconnect = true
            isCleanSession = true
            if (config.username.isNotBlank()) userName = config.username
            if (config.password.isNotBlank()) password = config.password.toCharArray()
            val statusTopic = "gaming_assistant/${config.clientId}/status"
            setWill(statusTopic, "offline".toByteArray(), 1, true)
        }

        mqttClient?.connect(options, null, object : IMqttActionListener {
            override fun onSuccess(asyncActionToken: IMqttToken?) {
                publishStatus("online")
                CaptureStatusBus.update { it.copy(mqttConnected = true, lastError = "") }
            }

            override fun onFailure(asyncActionToken: IMqttToken?, exception: Throwable?) {
                pushError("MQTT connect failed: ${exception?.message}")
                CaptureStatusBus.update { it.copy(mqttConnected = false) }
            }
        })
    }

    private fun startCaptureLoop() {
        captureJob?.cancel()
        captureJob = serviceScope.launch {
            while (isActive) {
                runCatching { captureAndPublishFrame() }
                    .onFailure { pushError("Capture failed: ${it.message}") }
                delay(config.intervalSeconds.coerceAtLeast(1) * 1000L)
            }
        }
    }

    private fun captureAndPublishFrame() {
        val image = imageReader?.acquireLatestImage() ?: return
        image.use {
            val plane = image.planes.firstOrNull() ?: return
            val width = image.width
            val height = image.height
            val rowStride = plane.rowStride
            val pixelStride = plane.pixelStride
            val rowPadding = rowStride - pixelStride * width

            val bitmap = Bitmap.createBitmap(
                width + rowPadding / pixelStride,
                height,
                Bitmap.Config.ARGB_8888,
            )
            bitmap.copyPixelsFromBuffer(plane.buffer)
            val cropped = Bitmap.createBitmap(bitmap, 0, 0, width, height)

            val jpg = ByteArrayOutputStream().use { out ->
                cropped.compress(Bitmap.CompressFormat.JPEG, config.jpegQuality.coerceIn(1, 100), out)
                out.toByteArray()
            }

            publishBinary("gaming_assistant/${config.clientId}/image", jpg)
            publishMetadata(width, height)

            sentFrames += 1
            CaptureStatusBus.update {
                it.copy(serviceRunning = true, sentFrames = sentFrames, lastError = "")
            }
            updateNotification("Frames gesendet: $sentFrames")

            bitmap.recycle()
            cropped.recycle()
        }
    }

    private fun publishMetadata(width: Int, height: Int) {
        val meta = JSONObject().apply {
            put("client_type", "android")
            if (config.gameHint.isNotBlank()) put("window_title", config.gameHint)
            put("resolution", "${width}x$height")
            put("timestamp", System.currentTimeMillis())
            put("app_package", packageName)
        }
        publishBinary("gaming_assistant/${config.clientId}/meta", meta.toString().toByteArray())
    }

    private fun publishStatus(status: String) {
        publishBinary("gaming_assistant/${config.clientId}/status", status.toByteArray(), retained = true)
    }

    private fun publishBinary(topic: String, payload: ByteArray, retained: Boolean = false) {
        val client = mqttClient ?: return
        if (!client.isConnected) return
        val msg = MqttMessage(payload).apply {
            qos = 0
            isRetained = retained
        }
        client.publish(topic, msg)
    }

    private fun stopCaptureAndSelf() {
        stopCapture()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun stopCapture() {
        captureJob?.cancel()
        captureJob = null

        runCatching { publishStatus("offline") }

        virtualDisplay?.release()
        virtualDisplay = null

        imageReader?.close()
        imageReader = null

        mediaProjection?.stop()
        mediaProjection = null

        runCatching { mqttClient?.disconnectForcibly(0, 0) }
        mqttClient?.close()
        mqttClient = null

        sentFrames = 0
        CaptureStatusBus.reset()
    }

    private fun pushError(message: String) {
        CaptureStatusBus.update { it.copy(lastError = message) }
        updateNotification(message)
    }

    private fun buildNotification(content: String): Notification {
        ensureNotificationChannel()

        val stopIntent = Intent(this, CaptureService::class.java).apply { action = ACTION_STOP }
        val stopPi = PendingIntent.getService(
            this,
            1001,
            stopIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Gaming Assistant Capture")
            .setContentText(content)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .addAction(android.R.drawable.ic_media_pause, "Stop", stopPi)
            .build()
    }

    private fun updateNotification(content: String) {
        val mgr = getSystemService(NotificationManager::class.java)
        mgr.notify(NOTIF_ID, buildNotification(content))
    }

    private fun ensureNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val mgr = getSystemService(NotificationManager::class.java)
        val existing = mgr.getNotificationChannel(CHANNEL_ID)
        if (existing != null) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Capture Service",
            NotificationManager.IMPORTANCE_LOW,
        )
        mgr.createNotificationChannel(channel)
    }

    companion object {
        const val ACTION_START = "de.chancekonstruktion.gamingassistant.capture.START"
        const val ACTION_STOP = "de.chancekonstruktion.gamingassistant.capture.STOP"

        const val EXTRA_RESULT_CODE = "extra_result_code"
        const val EXTRA_RESULT_DATA = "extra_result_data"
        const val EXTRA_BROKER_HOST = "extra_broker_host"
        const val EXTRA_BROKER_PORT = "extra_broker_port"
        const val EXTRA_USERNAME = "extra_username"
        const val EXTRA_PASSWORD = "extra_password"
        const val EXTRA_CLIENT_ID = "extra_client_id"
        const val EXTRA_INTERVAL_SECONDS = "extra_interval_seconds"
        const val EXTRA_JPEG_QUALITY = "extra_jpeg_quality"
        const val EXTRA_GAME_HINT = "extra_game_hint"

        private const val CHANNEL_ID = "ga_capture_channel"
        private const val NOTIF_ID = 42001
        private const val RESULT_OK = -1
    }
}

@Suppress("DEPRECATION")
private inline fun <reified T> Intent.getParcelableExtraCompat(key: String): T? {
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        getParcelableExtra(key, T::class.java)
    } else {
        getParcelableExtra(key)
    }
}
