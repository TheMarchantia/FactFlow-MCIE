package com.factflow

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.factflow.capture.BubbleService
import com.factflow.capture.CaptureService
import com.factflow.ui.components.GlassBox
import com.factflow.ui.history.HistoryScreen

class MainActivity : ComponentActivity() {

    private val requestNotificationLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { }

    // Step 1 of the capture-consent chain: RECORD_AUDIO is a dangerous
    // runtime permission. It was already declared in the manifest, but
    // nothing previously requested it at runtime -- MediaRecorder's mic
    // source would have failed with a SecurityException on first use.
    private val requestAudioPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            requestScreenCaptureConsent()
        } else {
            Toast.makeText(this, "Microphone access is needed to verify a clip's audio.", Toast.LENGTH_LONG).show()
        }
    }

    // Step 2: the system's screen-capture consent dialog (Section 4.4).
    // Asked once per bubble session, not once per clip -- see
    // CaptureService's class doc for why a single consent is reused across
    // every two-tap recording in the session.
    private val requestScreenCaptureLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val data = result.data
        if (result.resultCode == RESULT_OK && data != null) {
            CaptureService.initSession(this, result.resultCode, data)
            val intent = Intent(this, BubbleService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
        } else {
            Toast.makeText(this, "Screen recording permission is required to verify a clip.", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestNotificationsIfNeeded()

        setContent {
            var currentScreen by remember { mutableStateOf("main") }
            FactFlowTheme {
                if (currentScreen == "main") {
                    MainScreen(
                        onStartBubble = ::startBubbleOrRequestPermissions,
                        onStopBubble = { stopService(Intent(this, BubbleService::class.java)) },
                        onViewHistory = { currentScreen = "history" },
                    )
                } else {
                    HistoryScreen(onBack = { currentScreen = "main" })
                }
            }
        }
    }

    private fun requestNotificationsIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            requestNotificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    /**
     * The full permission chain for "Enable verification bubble" (Section
     * 4.3): overlay permission, then microphone, then screen-capture
     * consent, in that order -- each step only runs if the previous one is
     * already satisfied, so a user who already granted everything gets
     * straight through to starting the bubble with no extra taps.
     */
    private fun startBubbleOrRequestPermissions() {
        if (!Settings.canDrawOverlays(this)) {
            startActivity(Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName"),
            ))
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestAudioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        requestScreenCaptureConsent()
    }

    private fun requestScreenCaptureConsent() {
        val projectionManager = getSystemService(MediaProjectionManager::class.java)
        requestScreenCaptureLauncher.launch(projectionManager.createScreenCaptureIntent())
    }
}

@Composable
private fun FactFlowTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Color(0xFFB9C9FF),
            onPrimary = Color(0xFF17213B),
            secondary = Color(0xFFAFC7FF),
            background = Color(0xFF0A1020),
            surface = Color(0xFF121D33),
            onSurface = Color(0xFFF2F5FF),
        ),
        content = content,
    )
}

@Composable
fun MainScreen(onStartBubble: () -> Unit, onStopBubble: () -> Unit, onViewHistory: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    listOf(Color(0xFF0A1020), Color(0xFF111D38), Color(0xFF0A1020)),
                ),
            ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 30.dp),
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text("FactFlow", fontSize = 30.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
                Spacer(Modifier.height(6.dp))
                Text(
                    "Verify what you are watching, without leaving the moment.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color(0xFFC4CEE4),
                )
            }

            GlassBox(
                modifier = Modifier.fillMaxWidth(),
                cornerRadius = 30.dp,
            ) {
                Column(
                    modifier = Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.Start,
                ) {
                    Text("OVERLAY CONTROL", fontSize = 11.sp, letterSpacing = 1.4.sp, color = Color(0xFFB9C9FF))
                    Spacer(Modifier.height(14.dp))
                    Text(
                        "Your verification control is ready.",
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.SemiBold,
                        color = Color.White,
                    )
                    Spacer(Modifier.height(10.dp))
                    Text(
                        "Tap once to start, once to finish. When a result is ready, double-tap the bubble to read it.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color(0xFFD2DAEC),
                        lineHeight = 21.sp,
                    )
                    Spacer(Modifier.height(24.dp))
                    Button(
                        onClick = onStartBubble,
                        modifier = Modifier.fillMaxWidth().height(54.dp),
                        shape = RoundedCornerShape(18.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Color(0xFFE6ECFF),
                            contentColor = Color(0xFF16213B),
                        ),
                    ) {
                        androidx.compose.material3.Icon(Icons.Default.PlayArrow, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Enable verification bubble", fontWeight = FontWeight.SemiBold)
                    }
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = onViewHistory,
                    modifier = Modifier.weight(1f).height(50.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFFE7ECFA)),
                    border = ButtonDefaults.outlinedButtonBorder.copy(brush = Brush.linearGradient(listOf(Color(0xFF93AAE0), Color(0xFF405474)))),
                ) {
                    androidx.compose.material3.Icon(Icons.Default.List, contentDescription = null)
                    Spacer(Modifier.width(7.dp))
                    Text("History")
                }
                OutlinedButton(
                    onClick = onStopBubble,
                    modifier = Modifier.weight(1f).height(50.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFFDABFC4)),
                    border = ButtonDefaults.outlinedButtonBorder.copy(brush = Brush.linearGradient(listOf(Color(0xFF8D5B68), Color(0xFF503741)))),
                ) {
                    androidx.compose.material3.Icon(Icons.Default.Close, contentDescription = null)
                    Spacer(Modifier.width(7.dp))
                    Text("Hide")
                }
            }
        }
    }
}
