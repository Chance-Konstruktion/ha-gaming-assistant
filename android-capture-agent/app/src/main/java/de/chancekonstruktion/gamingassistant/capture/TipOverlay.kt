package de.chancekonstruktion.gamingassistant.capture

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import kotlin.math.abs

/**
 * Shows the latest tip on top of the running game (GA-112).
 *
 * A small, semi-transparent box drawn over other apps. It never takes focus
 * and never catches touches outside itself; drag it to move it, tap it to
 * dismiss it until the next tip. It also hides itself after a while.
 * Display only: nothing here sends input to the game.
 *
 * Every call must come from the main thread.
 */
class TipOverlay(private val context: Context) {
    private val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val handler = Handler(Looper.getMainLooper())
    private var view: TextView? = null
    private val hideRunnable = Runnable { view?.visibility = View.GONE }

    /** Whether a tip is on screen right now. */
    val isShowing: Boolean
        get() = view?.visibility == View.VISIBLE

    fun show(text: String, durationMs: Long = DEFAULT_DURATION_MS) {
        if (!canDraw(context)) return
        val tv = view ?: createView().also { view = it }
        tv.text = text
        tv.visibility = View.VISIBLE
        handler.removeCallbacks(hideRunnable)
        handler.postDelayed(hideRunnable, durationMs)
    }

    /** Make the box invisible (but keep its place) while a screenshot is taken. */
    fun setHiddenForCapture(hidden: Boolean) {
        view?.alpha = if (hidden) 0f else 1f
    }

    fun dismiss() {
        handler.removeCallbacks(hideRunnable)
        view?.let { runCatching { windowManager.removeView(it) } }
        view = null
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun createView(): TextView {
        val metrics = context.resources.displayMetrics
        fun dp(value: Float): Int =
            TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, metrics).toInt()

        val tv = TextView(context).apply {
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 15f
            maxLines = 6
            maxWidth = (metrics.widthPixels * 0.9f).toInt()
            setPadding(dp(14f), dp(10f), dp(14f), dp(10f))
            background = GradientDrawable().apply {
                setColor(0xCC202124.toInt())
                cornerRadius = dp(12f).toFloat()
            }
        }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = dp(24f)
        }

        // Drag to move; a tap without movement dismisses the tip.
        var startX = 0
        var startY = 0
        var touchX = 0f
        var touchY = 0f
        var moved = false
        tv.setOnTouchListener { v, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x
                    startY = params.y
                    touchX = event.rawX
                    touchY = event.rawY
                    moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - touchX
                    val dy = event.rawY - touchY
                    if (abs(dx) > dp(4f) || abs(dy) > dp(4f)) moved = true
                    params.x = startX + dx.toInt()
                    params.y = startY + dy.toInt()
                    windowManager.updateViewLayout(v, params)
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!moved) {
                        handler.removeCallbacks(hideRunnable)
                        v.visibility = View.GONE
                    }
                    true
                }
                else -> false
            }
        }
        windowManager.addView(tv, params)
        return tv
    }

    companion object {
        const val DEFAULT_DURATION_MS = 12_000L

        /** Whether the user allowed "Display over other apps" for this app. */
        fun canDraw(context: Context): Boolean = Settings.canDrawOverlays(context)
    }
}
