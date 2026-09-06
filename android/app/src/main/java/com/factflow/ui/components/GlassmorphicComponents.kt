package com.factflow.ui.components

import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * A glassmorphic container inspired by iOS 26 "Liquid Glass".
 *
 * The blur is applied ONLY to a background layer, so child content (text,
 * buttons) stays sharp and readable. On Android < 12 where RenderEffect
 * isn't available, the background falls back to a higher-opacity gradient.
 */
@Composable
fun GlassBox(
    modifier: Modifier = Modifier,
    cornerRadius: Dp = 24.dp,
    blurRadius: Dp = 20.dp,
    content: @Composable BoxScope.() -> Unit
) {
    val isBlurSupported = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
    val shape = RoundedCornerShape(cornerRadius)

    Box(
        modifier = modifier.clip(shape)
    ) {
        // Layer 1 — blurred frosted background (or opaque fallback)
        Box(
            modifier = Modifier
                .matchParentSize()
                .then(
                    if (isBlurSupported) {
                        Modifier.blur(blurRadius)
                    } else {
                        Modifier
                    }
                )
                .background(
                    brush = Brush.verticalGradient(
                        colors = if (isBlurSupported) {
                            listOf(
                                Color.White.copy(alpha = 0.25f),
                                Color.White.copy(alpha = 0.1f)
                            )
                        } else {
                            // Higher opacity fallback when blur isn't available
                            listOf(
                                Color.White.copy(alpha = 0.85f),
                                Color.White.copy(alpha = 0.7f)
                            )
                        }
                    )
                )
                .border(
                    width = 1.dp,
                    brush = Brush.verticalGradient(
                        colors = listOf(
                            Color.White.copy(alpha = 0.5f),
                            Color.Transparent,
                            Color.White.copy(alpha = 0.2f)
                        )
                    ),
                    shape = shape
                )
        )

        // Layer 2 — sharp, readable content on top
        content()
    }
}
