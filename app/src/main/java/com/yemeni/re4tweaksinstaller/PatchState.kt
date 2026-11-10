package com.yemeni.re4tweaksinstaller

import android.os.Handler
import android.os.Looper

/**
 * State shared between [PatchService] (which does the work, so it keeps going
 * when the app is left or closed) and [MainActivity] (which only shows it).
 * It lives as long as the app's process does.
 */
object PatchState {

    class Result(val ok: Boolean, val text: String, val outputPath: String)

    interface Listener {
        fun onPatchStarted(label: String)
        fun onPatchFinished(result: Result)
    }

    private val main = Handler(Looper.getMainLooper())

    @Volatile var running = false
        private set

    @Volatile var runningLabel: String = ""
        private set

    /** A finished result the screen has not shown yet (the app was not visible). */
    @Volatile var pendingResult: Result? = null

    /** True while the activity is on screen. Used to decide on notifications. */
    @Volatile var appVisible = false

    @Volatile var listener: Listener? = null

    /** Returns false when a patch is already running. */
    @Synchronized
    fun begin(label: String): Boolean {
        if (running) return false
        running = true
        runningLabel = label
        pendingResult = null
        main.post { listener?.onPatchStarted(label) }
        return true
    }

    @Synchronized
    fun finish(result: Result) {
        running = false
        pendingResult = result
        main.post { listener?.onPatchFinished(result) }
    }
}
