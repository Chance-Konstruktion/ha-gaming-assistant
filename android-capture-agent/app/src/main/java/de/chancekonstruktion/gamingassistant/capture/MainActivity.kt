package de.chancekonstruktion.gamingassistant.capture

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.widget.doAfterTextChanged
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import de.chancekonstruktion.gamingassistant.capture.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private val viewModel: MainViewModel by viewModels()

    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startCaptureService(result.resultCode, result.data!!)
        } else {
            Toast.makeText(this, "Screen capture permission denied", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        bindInputs()
        bindButtons()
        observeState()
    }

    private fun bindInputs() {
        binding.etBroker.doAfterTextChanged {
            viewModel.updateConfig { cfg -> cfg.copy(brokerHost = it.toString()) }
        }
        binding.etPort.doAfterTextChanged {
            val value = it.toString().toIntOrNull() ?: 1883
            viewModel.updateConfig { cfg -> cfg.copy(brokerPort = value) }
        }
        binding.etUsername.doAfterTextChanged {
            viewModel.updateConfig { cfg -> cfg.copy(username = it.toString()) }
        }
        binding.etPassword.doAfterTextChanged {
            viewModel.updateConfig { cfg -> cfg.copy(password = it.toString()) }
        }
        binding.etClientId.doAfterTextChanged {
            viewModel.updateConfig { cfg -> cfg.copy(clientId = it.toString()) }
        }
        binding.etInterval.doAfterTextChanged {
            val value = it.toString().toIntOrNull()?.coerceAtLeast(1) ?: 5
            viewModel.updateConfig { cfg -> cfg.copy(intervalSeconds = value) }
        }
        binding.etQuality.doAfterTextChanged {
            val value = (it.toString().toIntOrNull() ?: 70).coerceIn(1, 100)
            viewModel.updateConfig { cfg -> cfg.copy(jpegQuality = value) }
        }
        binding.etGameHint.doAfterTextChanged {
            viewModel.updateConfig { cfg -> cfg.copy(gameHint = it.toString()) }
        }
    }

    private fun bindButtons() {
        binding.btnStart.setOnClickListener {
            val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            projectionLauncher.launch(mgr.createScreenCaptureIntent())
        }

        binding.btnStop.setOnClickListener {
            val intent = Intent(this, CaptureService::class.java).apply {
                action = CaptureService.ACTION_STOP
            }
            startService(intent)
        }
    }

    private fun observeState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                launch {
                    viewModel.config.collect { config ->
                        if (binding.etBroker.text.toString() != config.brokerHost) binding.etBroker.setText(config.brokerHost)
                        if (binding.etPort.text.toString() != config.brokerPort.toString()) binding.etPort.setText(config.brokerPort.toString())
                        if (binding.etUsername.text.toString() != config.username) binding.etUsername.setText(config.username)
                        if (binding.etPassword.text.toString() != config.password) binding.etPassword.setText(config.password)
                        if (binding.etClientId.text.toString() != config.clientId) binding.etClientId.setText(config.clientId)
                        if (binding.etInterval.text.toString() != config.intervalSeconds.toString()) binding.etInterval.setText(config.intervalSeconds.toString())
                        if (binding.etQuality.text.toString() != config.jpegQuality.toString()) binding.etQuality.setText(config.jpegQuality.toString())
                        if (binding.etGameHint.text.toString() != config.gameHint) binding.etGameHint.setText(config.gameHint)
                    }
                }
                launch {
                    viewModel.status.collect { status ->
                        val txt = "running=${status.serviceRunning}, mqtt=${status.mqttConnected}, frames=${status.sentFrames}"
                        binding.tvStatus.text = txt
                        binding.tvError.text = status.lastError
                    }
                }
            }
        }
    }

    private fun startCaptureService(resultCode: Int, data: Intent) {
        val cfg = viewModel.config.value
        val intent = Intent(this, CaptureService::class.java).apply {
            action = CaptureService.ACTION_START
            putExtra(CaptureService.EXTRA_RESULT_CODE, resultCode)
            putExtra(CaptureService.EXTRA_RESULT_DATA, data)
            putExtra(CaptureService.EXTRA_BROKER_HOST, cfg.brokerHost)
            putExtra(CaptureService.EXTRA_BROKER_PORT, cfg.brokerPort)
            putExtra(CaptureService.EXTRA_USERNAME, cfg.username)
            putExtra(CaptureService.EXTRA_PASSWORD, cfg.password)
            putExtra(CaptureService.EXTRA_CLIENT_ID, cfg.clientId)
            putExtra(CaptureService.EXTRA_INTERVAL_SECONDS, cfg.intervalSeconds)
            putExtra(CaptureService.EXTRA_JPEG_QUALITY, cfg.jpegQuality)
            putExtra(CaptureService.EXTRA_GAME_HINT, cfg.gameHint)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }
}
