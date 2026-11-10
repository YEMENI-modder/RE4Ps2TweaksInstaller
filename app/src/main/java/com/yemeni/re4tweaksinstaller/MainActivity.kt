package com.yemeni.re4tweaksinstaller

import android.Manifest
import android.content.ContentUris
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.provider.Settings
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.os.LocaleListCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.google.android.material.button.MaterialButton
import com.google.android.material.button.MaterialButtonToggleGroup
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.android.material.progressindicator.LinearProgressIndicator
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

/**
 * Overall flow:
 *   1. "Select ISO" opens the Storage Access Framework picker.
 *   2. Python's `open()` needs a real filesystem path. With "all files
 *      access" granted, the picked Uri is resolved to its real path and
 *      the ISO is read in place (no copy). If the path can't be resolved
 *      (or access was not granted), the content:// Uri is copied into
 *      the app's own files dir instead (slow for 1.4-4.7GB ISOs).
 *      When the real path is known and writable, the ISO is patched IN
 *      PLACE (same file name). With the backup option on (default), the
 *      untouched ISO is first copied to <name>_Og.iso. Otherwise (no file
 *      access) the patched copy goes to Download as <name>_Patched.
 *   3. "Apply patch" starts PatchService, a foreground service that calls
 *      iso_handler.run_full_patch(): region detection, ELF extraction, the
 *      unchanged patch() logic, optional backup, and re-injection of the
 *      executable. Because it is a service, the work continues when the app
 *      is left or closed, with a progress notification.
 *   4. The result (or the installer's own error message) is shown in the
 *      status panel; if the app is not on screen when it ends, a
 *      notification reports it together with the saved path.
 *
 * UI: dark OLED theme, three step cards + credits. The app language
 * (English / Arabic, with RTL) is switched with AppCompat per-app locales.
 */
class MainActivity : AppCompatActivity() {

    private enum class Status { INFO, SUCCESS, ERROR }

    private lateinit var languageButton: MaterialButton
    private lateinit var pickIsoButton: MaterialButton
    private lateinit var patchButton: MaterialButton
    private lateinit var variantToggleGroup: MaterialButtonToggleGroup
    private lateinit var progressBar: LinearProgressIndicator
    private lateinit var progressLabel: TextView
    private lateinit var applyHintText: TextView
    private lateinit var badge1Number: TextView
    private lateinit var badge1Done: ImageView
    private lateinit var isoInfoPanel: LinearLayout
    private lateinit var isoNameText: TextView
    private lateinit var regionPill: TextView
    private lateinit var modePill: TextView
    private lateinit var outputPathText: TextView
    private lateinit var fallbackNoteText: TextView
    private lateinit var outputLabelText: TextView
    private lateinit var backupInfoText: TextView
    private lateinit var backupRow: LinearLayout
    private lateinit var backupSwitch: MaterialSwitch
    private lateinit var backupOffWarning: TextView
    private lateinit var statusPanel: LinearLayout
    private lateinit var statusIcon: ImageView
    private lateinit var statusTitle: TextView
    private lateinit var statusBody: TextView

    private var localIsoPath: String? = null
    private var outputIsoPath: String? = null
    private var usingTempCopy = false
    private var fallbackNote = ""
    private var isoDisplayName: String? = null
    private var regionLabel: String? = null
    private var busy = false

    private val pickIsoLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) {
            onIsoPicked(uri)
        }
    }

    // Android 13+: the progress/result notifications need this permission. The
    // patch starts either way; without it only the notifications are hidden.
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { startPatchJob() }

    private val patchListener = object : PatchState.Listener {
        override fun onPatchStarted(label: String) {
            if (!busy) setBusy(true, label)
        }

        override fun onPatchFinished(result: PatchState.Result) {
            PatchState.pendingResult = null
            showPatchResult(result)
        }
    }

    // Only used on Android 6-10, where the classic storage permissions apply.
    private val legacyPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        languageButton = findViewById(R.id.languageButton)
        pickIsoButton = findViewById(R.id.pickIsoButton)
        patchButton = findViewById(R.id.patchButton)
        variantToggleGroup = findViewById(R.id.variantToggleGroup)
        progressBar = findViewById(R.id.progressBar)
        progressLabel = findViewById(R.id.progressLabel)
        applyHintText = findViewById(R.id.applyHintText)
        badge1Number = findViewById(R.id.badge1Number)
        badge1Done = findViewById(R.id.badge1Done)
        isoInfoPanel = findViewById(R.id.isoInfoPanel)
        isoNameText = findViewById(R.id.isoNameText)
        regionPill = findViewById(R.id.regionPill)
        modePill = findViewById(R.id.modePill)
        outputPathText = findViewById(R.id.outputPathText)
        fallbackNoteText = findViewById(R.id.fallbackNoteText)
        outputLabelText = findViewById(R.id.outputLabelText)
        backupInfoText = findViewById(R.id.backupInfoText)
        backupRow = findViewById(R.id.backupRow)
        backupSwitch = findViewById(R.id.backupSwitch)
        backupOffWarning = findViewById(R.id.backupOffWarning)
        statusPanel = findViewById(R.id.statusPanel)
        statusIcon = findViewById(R.id.statusIcon)
        statusTitle = findViewById(R.id.statusTitle)
        statusBody = findViewById(R.id.statusBody)

        // Chaquopy requires explicit start before first use, exactly once per
        // process. The bundled Python files are extracted from the APK on the
        // first call.
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        findViewById<TextView>(R.id.versionText).text =
            getString(R.string.version_format, appVersionName())

        languageButton.setOnClickListener { toggleAppLanguage() }
        findViewById<MaterialButton>(R.id.githubButton).setOnClickListener { openUrl(GITHUB_URL) }
        // Credits for the original tweak's authors: each button carries its URL in `tag`.
        val tweakLinks = findViewById<LinearLayout>(R.id.tweakLinks)
        for (i in 0 until tweakLinks.childCount) {
            val link = tweakLinks.getChildAt(i)
            (link.tag as? String)?.let { url -> link.setOnClickListener { openUrl(url) } }
        }

        variantToggleGroup.addOnButtonCheckedListener { _, _, _ -> updateVariantIcons() }
        updateVariantIcons()

        pickIsoButton.setOnClickListener {
            if (!hasAllFilesAccess() && requestAllFilesAccess()) {
                showStatus(Status.INFO, getString(R.string.perm_title), getString(R.string.perm_body))
                return@setOnClickListener
            }
            pickIsoLauncher.launch(PICKER_MIME_TYPES)
        }
        patchButton.setOnClickListener { runPatch() }

        // Backup is ON by default; the choice is remembered between launches.
        backupSwitch.isChecked = getSharedPreferences(PREFS, MODE_PRIVATE)
            .getBoolean(PREF_BACKUP, true)
        backupSwitch.setOnCheckedChangeListener { _, checked ->
            getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                .putBoolean(PREF_BACKUP, checked).apply()
            renderIsoInfo()
        }

        restoreState(savedInstanceState)
        renderIsoInfo()
    }

    override fun onStart() {
        super.onStart()
        PatchState.appVisible = true
        PatchState.listener = patchListener
        syncWithPatchState()
    }

    override fun onStop() {
        super.onStop()
        PatchState.appVisible = false
        if (PatchState.listener === patchListener) PatchState.listener = null
    }

    /** Picks up a patch that is running, or finished while the app was not on screen. */
    private fun syncWithPatchState() {
        if (PatchState.running) {
            hideStatus()
            setBusy(true, PatchState.runningLabel)
            return
        }
        val pending = PatchState.pendingResult ?: return
        PatchState.pendingResult = null
        showPatchResult(pending)
    }

    private fun showPatchResult(result: PatchState.Result) {
        setBusy(false)
        NotificationManagerCompat.from(this).cancel(PatchService.NOTIF_DONE)
        if (result.ok) {
            showStatus(Status.SUCCESS, getString(R.string.patch_success_title), result.text)
        } else {
            showStatus(Status.ERROR, getString(R.string.patch_error_title), result.text)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString("iso", localIsoPath)
        outState.putString("out", outputIsoPath)
        outState.putBoolean("temp", usingTempCopy)
        outState.putString("note", fallbackNote)
        outState.putString("name", isoDisplayName)
        outState.putString("region", regionLabel)
    }

    private fun restoreState(state: Bundle?) {
        if (state == null) return
        localIsoPath = state.getString("iso")
        outputIsoPath = state.getString("out")
        usingTempCopy = state.getBoolean("temp")
        fallbackNote = state.getString("note") ?: ""
        isoDisplayName = state.getString("name")
        regionLabel = state.getString("region")
    }

    // ---------------------------------------------------------------- UI state

    private fun appVersionName(): String =
        try {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(packageName, 0).versionName ?: ""
        } catch (e: Exception) {
            ""
        }

    private fun toggleAppLanguage() {
        if (busy) {
            Toast.makeText(this, R.string.busy_cannot_switch_language, Toast.LENGTH_SHORT).show()
            return
        }
        val isArabic = resources.configuration.locales[0].language == "ar"
        AppCompatDelegate.setApplicationLocales(
            LocaleListCompat.forLanguageTags(if (isArabic) "en" else "ar")
        )
    }

    private fun openUrl(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (e: Exception) {
            Toast.makeText(this, R.string.no_browser, Toast.LENGTH_LONG).show()
        }
    }

    /** The selected menu language also gets a check mark, so colour is not the only cue. */
    private fun updateVariantIcons() {
        val checkedId = variantToggleGroup.checkedButtonId
        for (i in 0 until variantToggleGroup.childCount) {
            val button = variantToggleGroup.getChildAt(i) as? MaterialButton ?: continue
            button.icon = if (button.id == checkedId) {
                ContextCompat.getDrawable(this, R.drawable.ic_check)
            } else {
                null
            }
        }
    }

    private fun variantName(): String = when (variantToggleGroup.checkedButtonId) {
        R.id.btnEnglish -> "english"
        R.id.btnArabic -> "arabic"
        else -> "original"
    }

    private fun variantLabel(): String = when (variantToggleGroup.checkedButtonId) {
        R.id.btnEnglish -> getString(R.string.lang_english)
        R.id.btnArabic -> getString(R.string.lang_arabic)
        else -> getString(R.string.lang_original)
    }

    private fun setBusy(isBusy: Boolean, label: String? = null) {
        busy = isBusy
        progressBar.visibility = if (isBusy) View.VISIBLE else View.GONE
        progressLabel.visibility = if (isBusy) View.VISIBLE else View.GONE
        if (isBusy) progressLabel.text = label
        pickIsoButton.isEnabled = !isBusy
        languageButton.isEnabled = !isBusy
        backupSwitch.isEnabled = !isBusy
        for (i in 0 until variantToggleGroup.childCount) {
            variantToggleGroup.getChildAt(i).isEnabled = !isBusy
        }
        updateApplyEnabled()
    }

    private fun updateApplyEnabled() {
        val ready = localIsoPath != null
        patchButton.isEnabled = ready && !busy
        applyHintText.visibility = if (ready) View.GONE else View.VISIBLE
    }

    private fun showStatus(kind: Status, title: String, body: String?) {
        val (bg, icon, tint) = when (kind) {
            Status.SUCCESS -> Triple(R.drawable.bg_panel_success, R.drawable.ic_check_circle, R.color.success)
            Status.ERROR -> Triple(R.drawable.bg_panel_error, R.drawable.ic_alert_circle, R.color.error)
            Status.INFO -> Triple(R.drawable.bg_panel_info, R.drawable.ic_info, R.color.info)
        }
        statusPanel.setBackgroundResource(bg)
        statusIcon.setImageResource(icon)
        statusIcon.setColorFilter(ContextCompat.getColor(this, tint))
        statusTitle.text = title
        statusBody.text = body ?: ""
        statusBody.visibility = if (body.isNullOrBlank()) View.GONE else View.VISIBLE
        statusPanel.visibility = View.VISIBLE
    }

    private fun hideStatus() {
        statusPanel.visibility = View.GONE
    }

    /** Shows the picked ISO (or hides the panel) and updates step 1's badge. */
    private fun renderIsoInfo() {
        val has = localIsoPath != null
        isoInfoPanel.visibility = if (has) View.VISIBLE else View.GONE
        badge1Number.visibility = if (has) View.GONE else View.VISIBLE
        badge1Done.visibility = if (has) View.VISIBLE else View.GONE
        pickIsoButton.setText(if (has) R.string.select_other_iso else R.string.select_iso)
        if (has) {
            isoNameText.text = isoDisplayName ?: File(localIsoPath!!).name
            regionPill.text = getString(R.string.iso_region_format, regionLabel ?: "?")
            modePill.setText(if (usingTempCopy) R.string.iso_mode_copied else R.string.iso_mode_in_place)
            val inPlace = isInPlace()
            outputLabelText.setText(
                if (inPlace) R.string.iso_output_label_in_place else R.string.iso_output_label
            )
            outputPathText.text = outputIsoPath ?: ""
            val backup = backupPathOrNull()
            backupInfoText.text = if (backup != null) getString(R.string.iso_backup_format, backup) else ""
            backupInfoText.visibility = if (backup != null) View.VISIBLE else View.GONE
            fallbackNoteText.text = fallbackNote
            fallbackNoteText.visibility = if (fallbackNote.isBlank()) View.GONE else View.VISIBLE
        }
        // The backup switch only makes sense when the ISO itself gets patched.
        backupRow.visibility = if (has && !isInPlace()) View.GONE else View.VISIBLE
        backupOffWarning.visibility =
            if (!backupSwitch.isChecked && !(has && !isInPlace())) View.VISIBLE else View.GONE
        updateApplyEnabled()
    }

    /** True when the patch is written into the picked ISO itself. */
    private fun isInPlace(): Boolean =
        localIsoPath != null && outputIsoPath != null && localIsoPath == outputIsoPath

    /** <name>.iso -> <name>_Og.iso next to it; null when no backup will be made. */
    private fun backupPathOrNull(): String? {
        if (!isInPlace() || !backupSwitch.isChecked) return null
        val iso = File(localIsoPath!!)
        val dot = iso.name.lastIndexOf('.')
        val base = if (dot > 0) iso.name.substring(0, dot) else iso.name
        val ext = if (dot > 0) iso.name.substring(dot) else ".iso"
        return File(iso.parentFile, "${base}_Og$ext").absolutePath
    }

    private fun hasAllFilesAccess(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(
                this, Manifest.permission.WRITE_EXTERNAL_STORAGE
            ) == PackageManager.PERMISSION_GRANTED
        }

    /** Returns true if a permission screen/dialog was shown, false if it could not be opened. */
    private fun requestAllFilesAccess(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            return try {
                startActivity(
                    Intent(
                        Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:$packageName")
                    )
                )
                true
            } catch (e: Exception) {
                try {
                    startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                    true
                } catch (e2: Exception) {
                    false
                }
            }
        }
        legacyPermissionLauncher.launch(
            arrayOf(
                Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.WRITE_EXTERNAL_STORAGE
            )
        )
        return true
    }

    private fun queryDisplayName(uri: Uri): String? =
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { cursor -> if (cursor.moveToFirst()) cursor.getString(0) else null }

    private fun querySize(uri: Uri): Long? =
        try {
            contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)
                ?.use { cursor ->
                    if (cursor.moveToFirst() && !cursor.isNull(0)) cursor.getLong(0) else null
                }
        } catch (e: Exception) {
            null
        }

    /** Some providers still expose the real path through the legacy _data column. */
    private fun queryDataColumn(uri: Uri): String? =
        try {
            contentResolver.query(uri, arrayOf("_data"), null, null, null)
                ?.use { cursor -> if (cursor.moveToFirst()) cursor.getString(0) else null }
        } catch (e: Exception) {
            null
        }

    /** The kernel knows the real path of an open file: /proc/self/fd/N points at it. */
    private fun pathFromFileDescriptor(uri: Uri): String? =
        try {
            contentResolver.openFileDescriptor(uri, "r")?.use { pfd ->
                File("/proc/self/fd/${pfd.fd}").canonicalPath
            }
        } catch (e: Exception) {
            null
        }

    /**
     * Best-effort conversion of a picked document Uri into a real file path.
     * Several strategies are tried and a candidate is only accepted when the
     * file exists, is readable and has exactly the size the provider reports,
     * so a wrong guess can never be mistaken for the picked ISO.
     */
    private fun resolveRealPath(uri: Uri): String? {
        val candidates = ArrayList<String>()
        if (uri.scheme == "file") uri.path?.let { candidates.add(it) }

        if (DocumentsContract.isDocumentUri(this, uri)) {
            val docId = DocumentsContract.getDocumentId(uri)
            when (uri.authority) {
                "com.android.externalstorage.documents" -> {
                    val parts = docId.split(":", limit = 2)
                    if (parts.size == 2) {
                        val base = if (parts[0].equals("primary", ignoreCase = true)) {
                            Environment.getExternalStorageDirectory().absolutePath
                        } else {
                            "/storage/${parts[0]}"
                        }
                        candidates.add(File(base, parts[1]).path)
                    }
                }
                "com.android.providers.downloads.documents" -> {
                    if (docId.startsWith("raw:")) {
                        candidates.add(docId.removePrefix("raw:"))
                    } else {
                        docId.substringAfter(":").toLongOrNull()?.let { id ->
                            queryDataColumn(
                                ContentUris.withAppendedId(
                                    Uri.parse("content://downloads/public_downloads"), id
                                )
                            )?.let { candidates.add(it) }
                        }
                        queryDisplayName(uri)?.let { name ->
                            candidates.add(
                                File(
                                    Environment.getExternalStoragePublicDirectory(
                                        Environment.DIRECTORY_DOWNLOADS
                                    ),
                                    name
                                ).path
                            )
                        }
                    }
                }
                "com.android.providers.media.documents" -> {
                    docId.substringAfter(":").toLongOrNull()?.let { id ->
                        queryDataColumn(
                            ContentUris.withAppendedId(
                                MediaStore.Files.getContentUri("external"), id
                            )
                        )?.let { candidates.add(it) }
                    }
                }
            }
        }

        queryDataColumn(uri)?.let { candidates.add(it) }
        pathFromFileDescriptor(uri)?.let { candidates.add(it) }

        val expectedSize = querySize(uri)
        return candidates.firstOrNull { path ->
            val f = File(path)
            f.isFile && f.canRead() && (expectedSize == null || f.length() == expectedSize)
        }
    }

    /** <name>.iso -> <name>_Patched.iso, in the original's folder when known. */
    private fun buildOutputPath(displayName: String, sourceFile: File?): String {
        val dot = displayName.lastIndexOf('.')
        val base = if (dot > 0) displayName.substring(0, dot) else displayName
        val ext = if (dot > 0) displayName.substring(dot) else ".iso"
        val sourceDir: File? = sourceFile?.parentFile?.takeIf { it.canWrite() }
        val dir: File = when {
            sourceDir != null -> sourceDir
            hasAllFilesAccess() ->
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            else -> getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: filesDir
        }
        dir.mkdirs()
        return File(dir, "${base}_Patched$ext").absolutePath
    }

    /** Only .iso and .chd files are accepted (case-insensitive). */
    private fun isAllowedImageName(name: String?): Boolean {
        val ext = name?.substringAfterLast('.', "")?.lowercase() ?: return false
        return ext == "iso" || ext == "chd"
    }

    private fun onIsoPicked(uri: Uri) {
        val pickedName = queryDisplayName(uri)
        if (!isAllowedImageName(pickedName)) {
            Toast.makeText(this, R.string.unsupported_file_toast, Toast.LENGTH_LONG).show()
            showStatus(
                Status.ERROR,
                getString(R.string.unsupported_file_title),
                getString(R.string.unsupported_file_body)
            )
            return
        }
        val displayName = pickedName ?: "game.iso"
        val realFile: File? = if (hasAllFilesAccess()) {
            resolveRealPath(uri)?.let { File(it) }
        } else {
            null
        }
        // In-place patching needs a real path AND write access to that file.
        val writable = realFile != null && realFile.canWrite()
        fallbackNote = when {
            writable -> ""
            realFile != null -> getString(R.string.note_not_writable)
            !hasAllFilesAccess() -> getString(R.string.note_no_access)
            else -> getString(R.string.note_folder_not_found)
        }
        outputIsoPath = if (writable) realFile!!.absolutePath else buildOutputPath(displayName, realFile)
        isoDisplayName = displayName
        hideStatus()

        if (realFile != null) {
            usingTempCopy = false
            detectRegion(realFile.absolutePath)
        } else {
            copyIsoToLocalStorage(uri)
        }
    }

    /** Reads the boot executable name to show the region; patch() re-verifies everything later. */
    private fun detectRegion(isoPath: String) {
        setBusy(true, getString(R.string.working_reading))

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val detection = Python.getInstance()
                    .getModule("iso_handler")
                    .callAttr("find_boot_executable", isoPath)
                val region = detection.asList()[0].toString()

                withContext(Dispatchers.Main) {
                    localIsoPath = isoPath
                    regionLabel = region
                    setBusy(false)
                    renderIsoInfo()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { onIsoReadFailed(e) }
            }
        }
    }

    private fun onIsoReadFailed(e: Exception) {
        localIsoPath = null
        regionLabel = null
        setBusy(false)
        renderIsoInfo()
        showStatus(Status.ERROR, getString(R.string.read_error_title), e.message)
    }

    private fun copyIsoToLocalStorage(uri: Uri) {
        setBusy(true, getString(R.string.working_copying))

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val destFile = File(filesDir, "input_game.iso")
                contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(destFile).use { output ->
                        input.copyTo(output, bufferSize = 8 * 1024 * 1024)
                    }
                }

                val detection = Python.getInstance()
                    .getModule("iso_handler")
                    .callAttr("find_boot_executable", destFile.absolutePath)
                val region = detection.asList()[0].toString()

                withContext(Dispatchers.Main) {
                    localIsoPath = destFile.absolutePath
                    usingTempCopy = true
                    regionLabel = region
                    setBusy(false)
                    renderIsoInfo()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { onIsoReadFailed(e) }
            }
        }
    }

    private fun runPatch() {
        if (localIsoPath == null || outputIsoPath == null) return
        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED &&
            !prefs.getBoolean(PREF_ASKED_NOTIFICATIONS, false)
        ) {
            prefs.edit().putBoolean(PREF_ASKED_NOTIFICATIONS, true).apply()
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        startPatchJob()
    }

    /** Hands the work to PatchService so it survives leaving or closing the app. */
    private fun startPatchJob() {
        val isoPath = localIsoPath ?: return
        val outPath = outputIsoPath ?: return
        if (busy) return
        val backupPath = backupPathOrNull()
        val label = variantLabel()

        hideStatus()
        setBusy(
            true,
            if (backupPath != null) getString(R.string.working_backup_patching, label)
            else getString(R.string.working_patching, label)
        )

        val intent = Intent(this, PatchService::class.java).apply {
            action = PatchService.ACTION_START
            putExtra(PatchService.EXTRA_ISO, isoPath)
            putExtra(PatchService.EXTRA_OUT, outPath)
            putExtra(PatchService.EXTRA_VARIANT, variantName())
            putExtra(PatchService.EXTRA_BACKUP, backupPath)
            putExtra(PatchService.EXTRA_RUNNING_TITLE, getString(R.string.notif_running_title))
            putExtra(PatchService.EXTRA_RUNNING_TEXT, getString(R.string.notif_running_text, label))
            putExtra(PatchService.EXTRA_DONE_TITLE, getString(R.string.notif_done_title))
            putExtra(PatchService.EXTRA_ERROR_TITLE, getString(R.string.notif_error_title))
            putExtra(PatchService.EXTRA_SAVED_TEXT, getString(R.string.notif_saved_to, outPath))
            // "%s" is replaced by the service with the actual error message.
            putExtra(PatchService.EXTRA_UNEXPECTED_FMT, getString(R.string.unexpected_error, "%s"))
        }
        try {
            ContextCompat.startForegroundService(this, intent)
        } catch (e: Exception) {
            setBusy(false)
            showStatus(
                Status.ERROR,
                getString(R.string.patch_error_title),
                getString(R.string.unexpected_error, e.message ?: "")
            )
        }
    }

    private companion object {
        const val PREFS = "settings"
        const val PREF_BACKUP = "backup_enabled"
        const val PREF_ASKED_NOTIFICATIONS = "asked_notifications"
        // Hint for the system file picker: ISO and CHD images. Providers often report
        // them as octet-stream, so that type is included; the name is checked after.
        val PICKER_MIME_TYPES = arrayOf(
            "application/x-iso9660-image",
            "application/x-cd-image",
            "application/x-chd",
            "application/octet-stream"
        )
        const val GITHUB_URL = "https://github.com/YEMENI-modder"
    }
}
