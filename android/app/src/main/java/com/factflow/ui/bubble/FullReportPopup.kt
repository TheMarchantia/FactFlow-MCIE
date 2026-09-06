package com.factflow.ui.bubble

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.util.DisplayMetrics
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.factflow.network.ClaimVerdict
import com.factflow.network.Source
import com.factflow.network.VerdictResponse
import kotlin.math.roundToInt

/**
 * The "Full Verification Report" screen described in Section 4.7 -- reached
 * from VerdictPopup's "View Full Details" button. Per the architecture doc,
 * this stays an overlay above the host app rather than launching a separate
 * Activity, preserving the core design principle that the user never has to
 * leave the app they were using to inspect a result.
 *
 * The doc's example content also mentions an "evidence timeline" and
 * "reverse-image or source matches" -- those aren't rendered here because
 * the current backend's VerdictResponse/ClaimVerdict schema (Chapter 12)
 * doesn't carry that data yet. This screen shows every field the backend
 * actually returns today (full claim, full summary, confidence, and the
 * COMPLETE source list rather than VerdictPopup's 3-source preview) and is
 * structured so the extra sections can be added once those fields exist.
 */
class FullReportPopup(private val context: Context) {

    private val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var popupView: View? = null

    fun show(verdict: VerdictResponse, onClose: () -> Unit) {
        if (popupView != null) return

        val claim = verdict.claims.firstOrNull()
        val root = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(16), dp(22), dp(20))
            background = roundedBackground(
                intArrayOf(Color.argb(250, 16, 25, 44), Color.argb(247, 28, 41, 66)),
                30f,
                Color.argb(90, 255, 255, 255),
            )
            elevation = dp(22).toFloat()
        }

        val dragHandle = View(context).apply {
            layoutParams = LinearLayout.LayoutParams(dp(40), dp(4)).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                bottomMargin = dp(14)
            }
            background = roundedBackground(intArrayOf(Color.argb(120, 255, 255, 255)), 8f)
        }
        root.addView(dragHandle)

        val header = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val title = label("VERIFICATION REPORT", 12f, true, Color.argb(200, 230, 236, 249)).apply {
            letterSpacing = 0.14f
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
            setPadding(0, dp(18), 0, 0)
        }

        content.addView(sectionLabel("CLAIM"))
        content.addView(
            label(claim?.claimText ?: "No claim was returned.", 18f, true, Color.WHITE).apply {
                setLineSpacing(dp(2).toFloat(), 1f)
                setPadding(0, dp(6), 0, dp(20))
            },
        )

        content.addView(sectionLabel("CONFIDENCE"))
        content.addView(confidenceMeter(claim?.confidence ?: 0).apply {
            (layoutParams as? LinearLayout.LayoutParams)?.topMargin = dp(6)
        })
        content.addView(View(context).apply {
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(20))
        })

        content.addView(sectionLabel("EXPLANATION"))
        content.addView(
            label(claim?.summary ?: "No explanation is available.", 15f, false, Color.argb(224, 233, 239, 250)).apply {
                setLineSpacing(dp(4).toFloat(), 1f)
                setPadding(0, dp(6), 0, dp(20))
            },
        )

        val sources = claim?.sources.orEmpty()
        content.addView(sectionLabel(if (sources.isEmpty()) "SOURCES" else "SOURCES (${sources.size})"))
        if (sources.isEmpty()) {
            content.addView(
                label("No sources were returned for this verdict.", 14f, false, Color.argb(190, 210, 218, 235)).apply {
                    setPadding(0, dp(6), 0, 0)
                },
            )
        } else {
            sources.forEach { source ->
                content.addView(sourceRow(source).apply {
                    (layoutParams as? LinearLayout.LayoutParams)?.topMargin = dp(8)
                })
            }
        }

        scroll.addView(content)
        root.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        val close = TextView(context).apply {
            text = "Close"
            textSize = 14f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setPadding(dp(16), dp(13), dp(16), dp(13))
            background = roundedBackground(intArrayOf(Color.argb(66, 255, 255, 255)), 16f)
            setOnClickListener {
                dismiss()
                onClose()
            }
        }
        root.addView(close, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(18)
        })

        val overlayType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        }
        val metrics = DisplayMetrics().also {
            @Suppress("DEPRECATION") windowManager.defaultDisplay.getRealMetrics(it)
        }
        // Roomier than the compact VerdictPopup, since this is meant to hold
        // a full explanation and an unbounded source list -- but capped so
        // it never exceeds the visible screen on smaller devices.
        val width = minOf(dp(380), (metrics.widthPixels * 0.9f).roundToInt())
        val height = minOf(dp(620), (metrics.heightPixels * 0.82f).roundToInt())

        val params = WindowManager.LayoutParams(
            width, height, overlayType,
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

    private fun sourceRow(source: Source): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(14), dp(10), dp(14), dp(10))
        background = roundedBackground(intArrayOf(Color.argb(28, 255, 255, 255)), 14f)
        addView(label(source.name, 14f, true, Color.WHITE))
        addView(
            label(hostOf(source.url), 12f, false, Color.argb(190, 199, 218, 255)).apply {
                setPadding(0, dp(2), 0, 0)
            },
        )
        // Opening a source is an explicit choice the user made by tapping it
        // -- leaving the overlay context here is the correct interaction,
        // not a violation of "never leave the host app" (that principle
        // covers the verification flow itself, not a user-requested link).
        setOnClickListener {
            runCatching {
                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(source.url)).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(intent)
            }
        }
    }

    private fun hostOf(url: String): String = runCatching { Uri.parse(url).host }.getOrNull() ?: url

    private fun confidenceMeter(confidence: Int): LinearLayout {
        val clamped = confidence.coerceIn(0, 100)
        val container = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val fillColor = when {
            clamped >= 75 -> Color.rgb(77, 198, 147)
            clamped >= 45 -> Color.rgb(237, 178, 82)
            else -> Color.rgb(242, 99, 112)
        }
        // A two-segment weighted row (filled : empty = clamped : 100-clamped)
        // renders an exactly proportional bar regardless of the track's
        // actual measured width -- no assumption about a fixed pixel width
        // needed, unlike computing the fill's width against a guessed track
        // size ahead of layout.
        val track = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            background = roundedBackground(intArrayOf(Color.argb(40, 255, 255, 255)), 6f)
        }
        val filledSegment = View(context).apply {
            if (clamped > 0) background = roundedBackground(intArrayOf(fillColor), 6f)
        }
        val emptySegment = View(context)
        val filledWeight = clamped.coerceAtLeast(1).toFloat()
        val emptyWeight = (100 - clamped).coerceAtLeast(1).toFloat()
        track.addView(filledSegment, LinearLayout.LayoutParams(0, dp(10), filledWeight))
        if (clamped < 100) {
            track.addView(emptySegment, LinearLayout.LayoutParams(0, dp(10), emptyWeight))
        }
        container.addView(track, LinearLayout.LayoutParams(0, dp(10), 1f).apply { marginEnd = dp(12) })
        container.addView(label("$clamped%", 14f, true, Color.WHITE))
        return container
    }

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