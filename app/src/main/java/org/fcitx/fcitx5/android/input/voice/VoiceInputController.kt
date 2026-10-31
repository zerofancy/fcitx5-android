/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.inputmethod.InputConnection
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import org.fcitx.fcitx5.android.R
import org.fcitx.fcitx5.android.input.FcitxInputMethodService
import java.util.concurrent.Executors

/** UI/editor ownership is main-thread only. Worker callbacks are fenced by session identity. */
class VoiceInputController(private val service: FcitxInputMethodService) {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { Thread(it, "qwen-asr") }
    private val engine = QwenEngine(service.applicationContext)
    private val releaseIdle = Runnable { if (!worker.isShutdown) worker.execute { engine.close() } }
    private var session: VoiceSession? = null
    private var connection: InputConnection? = null
    private var generation = 0L
    private var busy = false
    private var held = false
    private var trimRequested = false
    private val timeout = Runnable {
        if (active) { cancel(); service.voiceMessage(message(R.string.voice_failed)) }
    }
    var active = false
        private set
    var status: String? = null
        private set

    private fun status(value: String?) { status = value; service.showVoiceStatus(value) }
    private fun message(id: Int) = service.getString(id)
    private fun valid(token: Long) = active && token == generation &&
        connection === service.currentInputConnection && service.isInputViewShown

    fun start() {
        if (busy || active || worker.isShutdown) return
        val info = service.currentInputEditorInfo ?: return
        val type = info.inputType
        val variation = type and InputType.TYPE_MASK_VARIATION
        val password = if (type and InputType.TYPE_MASK_CLASS == InputType.TYPE_CLASS_NUMBER)
            variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD else variation in setOf(
                InputType.TYPE_TEXT_VARIATION_PASSWORD, InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD,
                InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD)
        val problem = when {
            !org.fcitx.fcitx5.android.BuildConfig.VOICE_MODEL_BUNDLED -> R.string.voice_build_required
            !Build.SUPPORTED_ABIS.contains("arm64-v8a") -> R.string.voice_arm64_required
            type == InputType.TYPE_NULL || password || service.currentInputSelection.start < 0 ||
                service.currentInputSelection.start != service.currentInputSelection.end -> R.string.voice_editor_unavailable
            ContextCompat.checkSelfPermission(service, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED -> R.string.voice_setup_required
            !VoiceModel.ready(service) -> R.string.voice_setup_required
            else -> null
        }
        if (problem != null) { service.voiceMessage(message(problem)); return }
        if (!service.isInputViewShown) return
        connection = service.currentInputConnection ?: return
        main.removeCallbacks(releaseIdle)
        val token = ++generation
        held = true
        trimRequested = false
        active = true
        busy = true
        status(message(R.string.voice_starting))
        main.postDelayed(timeout, 10000)
        // Keep the visible preedit as-is, then discard the engine's pending preedit under ownership.
        service.finishComposing()
        service.lifecycleScope.launch {
            service.postFcitxJob { focusOutIn() }.join()
            if (!valid(token) || !held) {
                if (token == generation) cancel()
                busy = false
                return@launch
            }
            val current = VoiceSession()
            session = current
            worker.execute {
                var error: Throwable? = null
                try {
                    current.run(acquire = { engine.get() }, started = {
                        main.post { if (valid(token) && held) {
                            service.voiceStartedFeedback()
                            status(message(R.string.voice_loading))
                        } }
                    }, loaded = {
                        main.post { if (valid(token) && held) {
                            main.removeCallbacks(timeout)
                            status(message(R.string.voice_listening))
                        } }
                    }, show = { text ->
                        main.post { if (valid(token) && !service.setVoiceComposing(text)) {
                            cancel(); service.voiceMessage(message(R.string.voice_editor_unavailable))
                        } }
                    })
                } catch (e: Throwable) {
                    error = e
                    timber.log.Timber.w(e, "Offline voice input failed")
                }
                finally {
                    if (error != null) runCatching { engine.close() }
                    val failed = error != null
                    main.post {
                        busy = false
                        if (token == generation) {
                            main.removeCallbacks(timeout)
                            if (valid(token)) service.finishComposing()
                            active = false
                            session = null
                            connection = null
                            status(null)
                            if (trimRequested) releaseIdle.run() else main.postDelayed(releaseIdle, 60000)
                            if (failed) service.voiceMessage(message(R.string.voice_failed))
                        }
                    }
                }
            }
        }
    }

    fun release() {
        held = false
        if (!active) return
        main.removeCallbacks(timeout)
        main.postDelayed(timeout, 5000)
        status(message(R.string.voice_finishing))
        session?.stop()
    }

    /** Preserve the displayed text, invalidate all future results, never write into the next editor. */
    fun cancel(clearDraft: Boolean = false) {
        main.removeCallbacks(timeout)
        main.removeCallbacks(releaseIdle)
        if (!worker.isShutdown) worker.execute { engine.close() }
        if (active && clearDraft && connection === service.currentInputConnection) service.clearVoiceDraft()
        held = false
        if (active && connection === service.currentInputConnection) service.finishComposing()
        generation++
        active = false
        session?.cancel()
        session = null
        connection = null
        status(null)
    }

    fun trimMemory() {
        trimRequested = true
        if (!active && !worker.isShutdown) { main.removeCallbacks(releaseIdle); worker.execute { engine.close() } }
    }
    fun destroy() { cancel(); worker.shutdown() }
}
