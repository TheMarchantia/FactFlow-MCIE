package com.factflow.ui.bubble

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.factflow.network.ClaimVerdict
import com.factflow.network.VerdictResponse
import kotlin.math.roundToInt

/** A draggable, compact verification card rendered over the host application. */
class VerdictPopup(private val context: Context) {

    private val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var popupView: View? = null

    fun show(verdict: VerdictResponse, onClose: () -> Unit, onViewFullDetails: () -> Unit) {
        if (popupView != null) return

        val claim = verdict.claims.firstOrNull()
        val root = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(14), dp(20), dp(18))
            background = roundedBackground(
                intArrayOf(Color.argb(244, 20, 31, 52), Color.argb(240, 34, 49, 77)),
                28f,
                Color.argb(90, 255, 255, 255),
            )
            elevation = dp(18).toFloat()
        }

        val dragHandle = View(context).apply {
            layoutParams = LinearLayout.LayoutParams(dp(40), dp(4)).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                bottomMargin = dp(12)
            }
            background = roundedBackground(intArrayOf(Color.argb(120, 255, 255, 255)), 8f)
        }
        root.addView(dragHandle)

        val header = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val title = label("VERIFICATION READY", 11f, true, Color.argb(190, 230, 236, 249)).apply {
            letterSpacing = 0.12f
        }
        header.addView(title, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        header.addView(verdictBadge(claim))
        root.addView(header)

        val scroll = ScrollView(context).apply {
            isFillViewport = true
            overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
        }
        val content = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(16), 0, 0)
        }
        content.addView(sectionLabel("CLAIM"))
        content.addView(label(claim?.claimText ?: "No claim was returned.", 16f, true, Color.WHITE).apply {
            setPadding(0, dp(5), 0, dp(16))
        })
        content.addView(sectionLabel("SUMMARY"))
        content.addView(label(claim?.summary ?: "No explanation is available.", 14f, false, Color.argb(218, 233, 239, 250)).apply {
            setLineSpacing(dp(3).toFloat(), 1f)
            setPadding(0, dp(5), 0, dp(16))
        })

        val confidence = claim?.confidence ?: 0
        content.addView(label("Confidence  $confidence%", 13f, true, Color.WHITE).apply {
            background = roundedBackground(intArrayOf(Color.argb(48, 255, 255, 255)), 14f)
            setPadding(dp(12), dp(8), dp(12), dp(8))
        })

        claim?.sources?.take(3)?.takeIf { it.isNotEmpty() }?.let { sources ->
            content.addView(sectionLabel("SOURCES").apply { setPadding(0, dp(18), 0, dp(6)) })
            sources.forEach { source ->
                content.addView(label("•  ${source.name}", 13f, false, Color.argb(215, 199, 218, 255)).apply {
                    setPadding(0, dp(4), 0, dp(4))
                })
            }
        }
        scroll.addView(content)
        root.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        val close = TextView(context).apply {
            text = "Dismiss"
            textSize = 14f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setPadding(dp(16), dp(12), dp(16), dp(12))
            background = roundedBackground(intArrayOf(Color.argb(66, 255, 255, 255)), 16f)
            setOnClickListener {
                dismiss()
                onClose()
            }
        }
        val viewDetails = TextView(context).apply {
            text = "View Full Details"
            textSize = 14f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            gravity = Gravity.CENTER
            setTextColor(Color.argb(255, 22, 33, 59))
            setPadding(dp(16), dp(12), dp(16), dp(12))
            background = roundedBackground(intArrayOf(Color.argb(255, 230, 236, 255)), 16f)
            setOnClickListener {
                onViewFullDetails()
            }
        }
        val actions = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
        }
        actions.addView(
            viewDetails,
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = dp(8) },
        )
        actions.addView(close, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(actions, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(16)
        })

        val overlayType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        }
        val params = WindowManager.LayoutParams(
            dp(336), dp(460), overlayType,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            android.graphics.PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.CENTER }

        attachDragBehaviour(header, root, params)
        windowManager.addView(root, params)
        popupView = root
    }

    fun dismiss() {
        popupView?.let { runCatching { windowManager.removeView(it) } }
        popupView = null
    }

    fun isShowing(): Boolean = popupView != null

    private fun attachDragBehaviour(handle: View, root: View, params: WindowManager.LayoutParams) {
        var startX = 0
        var startY = 0
        var touchX = 0f
        var touchY = 0f
        handle.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x
                    startY = params.y
                    touchX = event.rawX
                    touchY = event.rawY
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = startX + (event.rawX - touchX).roundToInt()
                    params.y = startY + (event.rawY - touchY).roundToInt()
                    runCatching { windowManager.updateViewLayout(root, params) }
                    true
                }
                else -> true
            }
        }
    }

    private fun verdictBadge(claim: ClaimVerdict?): TextView {
        val verdict = claim?.verdict?.uppercase() ?: "UNKNOWN"
        val color = when (verdict) {
            "TRUE" -> Color.rgb(77, 198, 147)
            "FALSE" -> Color.rgb(242, 99, 112)
            "MISLEADING" -> Color.rgb(237, 178, 82)
            else -> Color.rgb(174, 186, 203)
        }
        return label(verdict, 11f, true, Color.WHITE).apply {
            background = roundedBackground(intArrayOf(color), 14f)
            setPadding(dp(10), dp(6), dp(10), dp(6))
        }
    }

    private fun sectionLabel(text: String): TextView = label(text, 10f, true, Color.argb(165, 204, 216, 238)).apply {
        letterSpacing = 0.12f
    }

    private fun label(text: String, sizeSp: Float, bold: Boolean, color: Int): TextView = TextView(context).apply {
        this.text = text
        textSize = sizeSp
        setTextColor(color)
        typeface = Typeface.create("sans-serif", if (bold) Typeface.BOLD else Typeface.NORMAL)
    }

    private fun roundedBackground(colors: IntArray, radius: Float, stroke: Int? = null): GradientDrawable {
        // GradientDrawable's gradient-colors constructor always builds a real
        // LinearGradient shader, which throws IllegalArgumentException
        // ("needs >= 2 number of colors") if given a single-element array --
        // use setColor() for the solid-color case instead.
        val drawable = if (colors.size == 1) {
            GradientDrawable().apply { setColor(colors[0]) }
        } else {
            GradientDrawable(GradientDrawable.Orientation.TL_BR, colors)
        }
        return drawable.apply {
            cornerRadius = dp(radius.roundToInt()).toFloat()
            stroke?.let { setStroke(dp(1), it) }
        }
    }

    private fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).roundToInt()
}