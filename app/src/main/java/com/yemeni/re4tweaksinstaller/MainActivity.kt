package com.yemeni.re4tweaksinstaller

import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.widget.Button
import android.widget.ProgressBar
import android.widget.RadioGroup
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

/**
 * Overall flow:
 *   1. User taps "Select ISO File" -> Storage Access Framework picker
 *      (ACTION_OPEN_DOCUMENT) opens, scoped to .iso / .bin extensions
 *      isn't natively filterable by MIME on all devices, so we accept
 *      "*/*" and just check the filename extension ourselves.
 *   2. We copy the picked content:// Uri into the app's own files dir
 *      as a plain file, because Python's `open()` cannot read a
 *      content:// Uri directly — it needs a real filesystem path.
 *      PS2 ISOs are commonly 1.4-4.7GB, so this copy is the slowest
 *      single step and is shown with a progress indicator.
 *   3. "Apply Patch" calls iso_handler.run_full_patch() on a background
 *      thread (Dispatchers.IO) — this already does region detection,
 *      ELF extraction, the actual patch() logic (unchanged from the
 *      original PC tool), and re-injects the result into a NEW output
 *      ISO (we never touch the user's original file).
 *   4. Result (success + output path, or a user-facing error message
 *      straight from patch()'s own fail() calls) is shown in statusText.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var statusText: TextView
    private lateinit var detectedRegionText: TextView
    private lateinit var pickIsoButton: Button
    private lateinit var patchButton: Button
    private lateinit var progressBar: ProgressBar
    private lateinit var variantRadioGroup: RadioGroup

    private var localIsoPath: String? = null

    private val pickIsoLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) {
            copyIsoToLocalStorage(uri)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        detectedRegionText = findViewById(R.id.detectedRegionText)
        pickIsoButton = findViewById(R.id.pickIsoButton)
        patchButton = findViewById(R.id.patchButton)
        progressBar = findViewById(R.id.progressBar)
        variantRadioGroup = findViewById(R.id.variantRadioGroup)

        // Chaquopy requires explicit start before first use, exactly
        // once per process. The bundled Python files (installer_core.py,
        // iso_handler.py, FilesUsed.py, RemoveWeaponSwap.py, dados/)
        // are extracted automatically from the APK's assets into the
        // app's private storage on first call — no manual unzip needed.
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        // Note: we no longer resolve a dados root path here directly —
        // run_full_patch() now takes a `variant` string ("original" /
        // "english") and resolves the correct root + installer_core.py
        // copy internally. See iso_handler.get_dados_root()'s docstring
        // for why each variant ships its own complete copy of
        // installer_core.py rather than sharing one with a swapped
        // dados/ folder.

        pickIsoButton.setOnClickListener {
            pickIsoLauncher.launch(arrayOf("*/*"))
        }

        patchButton.setOnClickListener {
            runPatch()
        }
    }

    private fun copyIsoToLocalStorage(uri: Uri) {
        statusText.text = "Copying ISO to local storage... this can take a minute for large files."
        progressBar.visibility = ProgressBar.VISIBLE
        pickIsoButton.isEnabled = false

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val destFile = File(filesDir, "input_game.iso")
                contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(destFile).use { output ->
                        input.copyTo(output, bufferSize = 8 * 1024 * 1024)
                    }
                }
                localIsoPath = destFile.absolutePath

                // Quick region peek so the user sees immediate feedback;
                // the real patch() call re-verifies everything anyway,
                // this is just a UX preview, not a security boundary.
                val detection = Python.getInstance()
                    .getModule("iso_handler")
                    .callAttr("find_boot_executable", localIsoPath)
                val region = detection.asList()[0].toString()

                withContext(Dispatchers.Main) {
                    progressBar.visibility = ProgressBar.GONE
                    pickIsoButton.isEnabled = true
                    detectedRegionText.text = "Detected region: $region"
                    statusText.text = "ISO loaded. Ready to patch."
                    patchButton.isEnabled = true
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    progressBar.visibility = ProgressBar.GONE
                    pickIsoButton.isEnabled = true
                    statusText.text = "Error reading ISO: ${e.message}"
                    detectedRegionText.text = ""
                    patchButton.isEnabled = false
                }
            }
        }
    }

    private fun runPatch() {
        val isoPath = localIsoPath ?: return

        val variant = if (variantRadioGroup.checkedRadioButtonId == R.id.radioEnglish) {
            "english"
        } else {
            "original"
        }

        statusText.text = "Patching ($variant menu)... please wait."
        progressBar.visibility = ProgressBar.VISIBLE
        patchButton.isEnabled = false
        pickIsoButton.isEnabled = false

        CoroutineScope(Dispatchers.IO).launch {
            val outputDir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            val outputIsoPath = File(outputDir, "RE4_Patched_${variant}_${System.currentTimeMillis()}.iso").absolutePath

            val result: PyObject = Python.getInstance()
                .getModule("iso_handler")
                .callAttr("run_full_patch", isoPath, outputIsoPath, variant)

            // result is a Python dict; asMap() has PyObject keys, so a String
            // lookup does not compile. Use dict.get() through callAttr instead.
            val ok = result.callAttr("get", "ok")?.toBoolean() ?: false

            withContext(Dispatchers.Main) {
                progressBar.visibility = ProgressBar.GONE
                pickIsoButton.isEnabled = true
                patchButton.isEnabled = true

                if (ok) {
                    val message = result.callAttr("get", "message")?.toString() ?: "Done."
                    statusText.text = "✅ $message"
                } else {
                    // These error strings come straight from the original
                    // installer's fail() calls (Parry conflict, corrupted
                    // data, unknown menu/HUD state, etc.) or from
                    // iso_handler's own IsoHandlerError — already written
                    // to be meaningful to the end user.
                    val error = result.callAttr("get", "error")?.toString() ?: "Unknown error."
                    statusText.text = "❌ $error"
                }
            }
        }
    }
}
