package com.factflow.ui.bubble

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.factflow.capture.RecordingManager

/**
 * Compact overlay control with deliberately restrained liquid-glass cues:
 * layered translucency, a moving highlight, and state-led motion. The text
 * itself is never blurred, which keeps the control legible over any host app.
 */
@Composable
fun BubbleComposeContent() {
    val state = RecordingManager.currentState
    val stage = RecordingManager.processingStage
    val verdict = RecordingManager.lastVerdict

    val targetColor = when (state) {
        RecordingManager.State.IDLE -> Color(0xFF6178A8)
        RecordingManager.State.RECORDING -> Color(0xFFEF5A66)
        RecordingManager.State.PROCESSING -> Color(0xFF6576FF)
        RecordingManager.State.ERROR -> Color(0xFF8B6B86)
        RecordingManager.State.DONE -> when (verdict?.claims?.firstOrNull()?.verdict?.uppercase()) {
            "TRUE" -> Color(0xFF45B98D)
            "FALSE" -> Color(0xFFE85F6A)
            "MISLEADING" -> Color(0xFFE6A94B)
            "INCONCLUSIVE" -> Color(0xFF9AA7B9)
            else -> Color(0xFF6178A8)
        }
    }
    val bubbleColor by animateColorAsState(targetColor, tween(450), label = "bubbleColor")
    val pulse = rememberInfiniteTransition(label = "bubblePulse")
    val pulseScale by pulse.animateFloat(
        initialValue = 1f,
        targetValue = if (state == RecordingManager.State.PROCESSING) 1.08f else 1.03f,
        animationSpec = infiniteRepeatable(tween(1200, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "pulseScale",
    )
    val haloAlpha by pulse.animateFloat(
        initialValue = 0.05f,
        targetValue = if (state == RecordingManager.State.RECORDING) 0.28f else 0.16f,
        animationSpec = infiniteRepeatable(tween(1000, easing = LinearEasing), RepeatMode.Reverse),
        label = "haloAlpha",
    )
    val sweepAngle by pulse.animateFloat(
        initialValue = -120f,
        targetValue = 240f,
        animationSpec = infiniteRepeatable(tween(1550, easing = LinearEasing), RepeatMode.Restart),
        label = "sweepAngle",
    )
    val displayedScale by animateFloatAsState(
        targetValue = if (state == RecordingManager.State.PROCESSING || state == RecordingManager.State.RECORDING) pulseScale else 1f,
        animationSpec = tween(250),
        label = "displayedScale",
    )

    Box(
        modifier = Modifier
            .size(64.dp)
            .graphicsLayer {
                scaleX = displayedScale
                scaleY = displayedScale
                shape = CircleShape
                clip = true
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            drawCircle(bubbleColor.copy(alpha = haloAlpha), radius = size.minDimension / 2f)
        }
        Box(
            modifier = Modifier
                .size(54.dp)
                .clip(CircleShape)
                .background(
                    Brush.radialGradient(
                        colors = listOf(
                            Color.White.copy(alpha = 0.92f),
                            bubbleColor.copy(alpha = 0.9f),
                            bubbleColor.copy(alpha = 0.74f),
                        ),
                    ),
                ),
            contentAlignment = Alignment.Center,
        ) {
            Canvas(Modifier.fillMaxSize()) {
                val radius = size.minDimension / 2f - 2.dp.toPx()
                drawCircle(Color.White.copy(alpha = 0.32f), radius = radius, style = Stroke(1.2.dp.toPx()))
                drawArc(
                    color = Color.White.copy(alpha = if (state == RecordingManager.State.PROCESSING) 0.72f else 0.32f),
                    startAngle = sweepAngle,
                    sweepAngle = 70f,
                    useCenter = false,
                    style = Stroke(2.dp.toPx(), cap = StrokeCap.Round),
                )
            }
            when (state) {
                RecordingManager.State.IDLE -> Text("FF", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                RecordingManager.State.RECORDING -> Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(7.dp).clip(CircleShape).background(Color.White))
                    Spacer(Modifier.width(5.dp))
                    Text("REC", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                }
                RecordingManager.State.PROCESSING -> Text(
                    text = stage?.take(5)?.uppercase() ?: "…",
                    color = Color.White,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                )
                RecordingManager.State.DONE -> Text("✓", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
                RecordingManager.State.ERROR -> Text("!", color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}
