package com.yemeni.re4tweaksinstaller

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Runs the patch in a foreground service so it is not interrupted when the
 * user leaves the app or swipes it away. A progress notification is shown
 * while it works and, if the app is not on screen when it ends, a result
 * notification says whether it worked and where the file was saved.
 *
 * All user-visible texts arrive in the Intent (already translated by the
 * activity), so the service needs no resources of its own except the two
 * notification channel names.
 */
class PatchService : Service() {

    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannels()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null || intent.action != ACTION_START) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val job = Job.from(intent)

        // startForeground must be reached quickly after startForegroundService().
        ServiceCompat.startForeground(
            this,
            NOTIF_RUNNING,
            buildRunningNotification(job),
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        )

        // A second tap while one patch is running is ignored.
        if (!PatchState.begin(job.runningText)) return START_NOT_STICKY

        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "re4tweaks:patch").apply {
            setReferenceCounted(false)
            acquire(MAX_RUN_MS)
        }

        Thread({ runJob(job) }, "patch-worker").start()
        return START_NOT_STICKY
    }

    private fun runJob(job: Job) {
        var ok = false
        var text: String
        try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(applicationContext))
            }
            val result = Python.getInstance()
                .getModule("iso_handler")
                .callAttr("run_full_patch", job.isoPath, job.outPath, job.variant, null, job.backupPath)
            // result is a Python dict; read it with dict.get() through callAttr.
            ok = result.callAttr("get", "ok")?.toBoolean() ?: false
            text = if (ok) {
                result.callAttr("get", "message")?.toString() ?: ""
            } else {
                result.callAttr("get", "error")?.toString() ?: ""
            }
        } catch (e: Throwable) {
            text = job.unexpectedFmt.replace("%s", e.message ?: "")
        }

        val result = PatchState.Result(ok, text, job.outPath)
        val appWasVisible = PatchState.appVisible
        PatchState.finish(result)

        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (e: Exception) {
            // ignore: lock already released
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        if (!appWasVisible) postDoneNotification(job, result)
        stopSelf()
    }

    // ------------------------------------------------------------ notifications

    private fun createChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(
                CH_PROGRESS, getString(R.string.notif_channel_progress),
                NotificationManager.IMPORTANCE_LOW
            )
        )
        nm.createNotificationChannel(
            NotificationChannel(
                CH_DONE, getString(R.string.notif_channel_done),
                NotificationManager.IMPORTANCE_DEFAULT
            )
        )
    }

    private fun openAppIntent(): PendingIntent {
        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        return PendingIntent.getActivity(
            this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
    }

    private fun buildRunningNotification(job: Job): Notification =
        NotificationCompat.Builder(this, CH_PROGRESS)
            .setSmallIcon(R.drawable.ic_disc)
            .setContentTitle(job.runningTitle)
            .setContentText(job.runningText)
            .setStyle(NotificationCompat.BigTextStyle().bigText(job.runningText))
            .setProgress(0, 0, true)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setContentIntent(openAppIntent())
            .build()

    private fun postDoneNotification(job: Job, result: PatchState.Result) {
        val title = if (result.ok) job.doneTitle else job.errorTitle
        val body = if (result.ok) job.savedText else result.text
        val notification = NotificationCompat.Builder(this, CH_DONE)
            .setSmallIcon(R.drawable.ic_disc)
            .setContentTitle(title)
            .setContentText(body.lineSequence().firstOrNull { it.isNotBlank() } ?: body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setContentIntent(openAppIntent())
            .build()
        try {
            NotificationManagerCompat.from(this).notify(NOTIF_DONE, notification)
        } catch (e: SecurityException) {
            // Notifications not allowed: the result is still shown when the app is opened.
        }
    }

    // ------------------------------------------------------------------- job

    private class Job(
        val isoPath: String,
        val outPath: String,
        val variant: String,
        val backupPath: String?,
        val runningTitle: String,
        val runningText: String,
        val doneTitle: String,
        val errorTitle: String,
        val savedText: String,
        val unexpectedFmt: String,
    ) {
        companion object {
            fun from(i: Intent) = Job(
                isoPath = i.getStringExtra(EXTRA_ISO) ?: "",
                outPath = i.getStringExtra(EXTRA_OUT) ?: "",
                variant = i.getStringExtra(EXTRA_VARIANT) ?: "original",
                backupPath = i.getStringExtra(EXTRA_BACKUP),
                runningTitle = i.getStringExtra(EXTRA_RUNNING_TITLE) ?: "",
                runningText = i.getStringExtra(EXTRA_RUNNING_TEXT) ?: "",
                doneTitle = i.getStringExtra(EXTRA_DONE_TITLE) ?: "",
                errorTitle = i.getStringExtra(EXTRA_ERROR_TITLE) ?: "",
                savedText = i.getStringExtra(EXTRA_SAVED_TEXT) ?: "",
                unexpectedFmt = i.getStringExtra(EXTRA_UNEXPECTED_FMT) ?: "%s",
            )
        }
    }

    companion object {
        const val ACTION_START = "com.yemeni.re4tweaksinstaller.action.START_PATCH"
        const val EXTRA_ISO = "iso"
        const val EXTRA_OUT = "out"
        const val EXTRA_VARIANT = "variant"
        const val EXTRA_BACKUP = "backup"
        const val EXTRA_RUNNING_TITLE = "running_title"
        const val EXTRA_RUNNING_TEXT = "running_text"
        const val EXTRA_DONE_TITLE = "done_title"
        const val EXTRA_ERROR_TITLE = "error_title"
        const val EXTRA_SAVED_TEXT = "saved_text"
        const val EXTRA_UNEXPECTED_FMT = "unexpected_fmt"

        const val NOTIF_RUNNING = 1001
        const val NOTIF_DONE = 1002
        private const val CH_PROGRESS = "patch_progress"
        private const val CH_DONE = "patch_done"
        private const val MAX_RUN_MS = 4L * 60 * 60 * 1000
    }
}
