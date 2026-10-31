/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.fcitx.fcitx5.android.R

class VoiceSetupActivity : AppCompatActivity() {
    private lateinit var status: TextView
    private lateinit var button: Button
    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        if (it) prepare() else status.setText(R.string.voice_permission_denied)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        status = TextView(this).apply { setText(R.string.voice_setup_description); textSize = 18f }
        button = Button(this).apply {
            setText(R.string.voice_prepare)
            setOnClickListener {
                if (ContextCompat.checkSelfPermission(this@VoiceSetupActivity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED)
                    prepare()
                else permission.launch(Manifest.permission.RECORD_AUDIO)
            }
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val padding = (24 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
            addView(status); addView(button)
        }
        val scroll = android.widget.ScrollView(this).apply { addView(content) }
        androidx.core.view.ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars() or
                androidx.core.view.WindowInsetsCompat.Type.displayCutout())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        setContentView(scroll)
        if (!org.fcitx.fcitx5.android.BuildConfig.VOICE_MODEL_BUNDLED) {
            status.setText(R.string.voice_build_required); button.isEnabled = false
        } else if (!Build.SUPPORTED_ABIS.contains("arm64-v8a")) {
            status.setText(R.string.voice_arm64_required); button.isEnabled = false
        }
    }

    private fun prepare() {
        button.isEnabled = false
        lifecycleScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    VoiceModel.prepare(applicationContext) { file ->
                        runOnUiThread { status.text = getString(R.string.voice_preparing, file) }
                    }
                }
            }
            status.setText(if (result.isSuccess) R.string.voice_ready else R.string.voice_prepare_failed)
            button.isEnabled = true
        }
    }
}
