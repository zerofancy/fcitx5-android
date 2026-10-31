package org.fcitx.voicep0

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.text.Editable
import android.text.TextWatcher
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.view.inputmethod.BaseInputConnection
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import java.util.UUID

class BenchActivity : Activity() {
    private lateinit var editor: EditText
    private lateinit var secondEditor: EditText
    private var active: BenchRun? = null
    private var hostLog: BenchLog? = null
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(24, 24, 24, 24) }
        layout.addView(TextView(this).apply { text = "Qwen3-ASR P0 · benchmark only"; textSize = 22f })
        editor = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            hint = "Partial composing appears here"
            minLines = 5
        }
        layout.addView(editor)
        secondEditor = EditText(this).apply { hint = "Second target (must not receive late results)" }
        layout.addView(secondEditor)
        editor.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val changed = clockMs()
                editor.post {
                    hostLog?.event("host_text", "changed_ms" to changed,
                        "composing_start" to BaseInputConnection.getComposingSpanStart(editor.text),
                        "composing_end" to BaseInputConnection.getComposingSpanEnd(editor.text),
                        "text" to editor.text.toString())
                }
            }
        })
        setContentView(layout)
        if (intent.hasExtra("id")) launch(intent)
        else {
            getSharedPreferences("run", MODE_PRIVATE).edit().clear().apply()
            editor.hint = "使用 tools/voice-p0/run.py 开始基准测试"
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.hasExtra("id")) launch(intent)
    }
    private fun launch(intent: Intent) {
        val id = intent.getStringExtra("id") ?: "manual-${UUID.randomUUID()}"
        require(id.matches(Regex("[A-Za-z0-9_-]+")))
        hostLog = BenchLog(this, id)
        val mode = intent.getStringExtra("mode") ?: "offline"
        if (mode == "production-host") {
            editor.requestFocus()
            editor.postDelayed({ getSystemService(InputMethodManager::class.java)
                .showSoftInput(editor, InputMethodManager.SHOW_IMPLICIT) }, 500)
            val handler = android.os.Handler(mainLooper)
            var last = ""
            val until = clockMs() + 180000
            val sample = object : Runnable {
                override fun run() {
                    if (isDestroyed || clockMs() > until) return
                    val start = BaseInputConnection.getComposingSpanStart(editor.text)
                    val end = BaseInputConnection.getComposingSpanEnd(editor.text)
                    val focused = if (editor.hasFocus()) 1 else if (secondEditor.hasFocus()) 2 else 0
                    val position = IntArray(2)
                    secondEditor.getLocationOnScreen(position)
                    val bounds = listOf(position[0], position[1], position[0] + secondEditor.width, position[1] + secondEditor.height)
                    val signature = "$start:$end:${editor.text}:${secondEditor.text}:$focused:$bounds"
                    if (signature != last) {
                        hostLog?.event("host_state", "composing_start" to start, "composing_end" to end,
                            "text" to editor.text.toString(), "second_text" to secondEditor.text.toString(), "focused_editor" to focused, "second_bounds" to org.json.JSONArray(bounds))
                        last = signature
                    }
                    handler.postDelayed(this, 100)
                }
            }
            handler.post(sample)
            val stimulusSeconds = intent.getIntExtra("stimulus_seconds", 0)
            if (stimulusSeconds > 0) Thread {
                Thread.sleep(5000)
                val source = readWave(java.io.File(filesDir, "fixtures/window-fast12.wav"))
                val pcm = ShortArray(source.size) { (source[it] * 24000).toInt().toShort() }
                val track = android.media.AudioTrack.Builder().setAudioAttributes(android.media.AudioAttributes.Builder()
                    .setUsage(android.media.AudioAttributes.USAGE_MEDIA).setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    .setAudioFormat(android.media.AudioFormat.Builder().setSampleRate(16000)
                        .setChannelMask(android.media.AudioFormat.CHANNEL_OUT_MONO).setEncoding(android.media.AudioFormat.ENCODING_PCM_16BIT).build())
                    .setTransferMode(android.media.AudioTrack.MODE_STREAM).setBufferSizeInBytes(6400).build()
                val manager = getSystemService(android.media.AudioManager::class.java)
                track.setPreferredDevice(manager.getDevices(android.media.AudioManager.GET_DEVICES_OUTPUTS)
                    .firstOrNull { it.type == android.media.AudioDeviceInfo.TYPE_BUILTIN_SPEAKER })
                try {
                    track.play()
                    hostLog?.event("stimulus_start", "route_type" to (track.routedDevice?.type ?: -1))
                    val end = clockMs() + stimulusSeconds * 1000
                    var offset = 0
                    while (clockMs() < end && !isDestroyed) {
                        val n = minOf(1600, pcm.size - offset)
                        val written = track.write(pcm, offset, n)
                        if (written <= 0) break
                        offset = (offset + written) % pcm.size
                    }
                } finally { track.stop(); track.release() }
            }.start()
            return
        }
        val seconds = intent.getIntExtra("seconds", 3).coerceAtLeast(1)
        val threads = intent.getIntExtra("threads", 3).coerceIn(1, 4)
        val repeats = intent.getIntExtra("repeats", 1).coerceIn(1, 30)
        val wave = intent.getStringExtra("wave") ?: "fixtures/fast1-16k.wav"
        val totalLen = intent.getIntExtra("total_len", 512)
        val memoryMode = intent.getStringExtra("memory_mode") ?: "default"
        val coreMs = intent.getIntExtra("core_ms", 2000)
        val overlapMs = intent.getIntExtra("overlap_ms", 1000)
        val hopMs = intent.getIntExtra("hop_ms", 500)
        val deadlineAware = intent.getBooleanExtra("deadline_aware", false)
        if (mode in listOf("ime-mic", "ime-replay", "ime-window", "ime-window-mic")) {
            getSharedPreferences("run", MODE_PRIVATE).edit().clear()
                .putString("id", id).putString("mode", when (mode) {
                    "ime-mic" -> "mic"; "ime-window" -> "window"; "ime-window-mic" -> "window-mic"; else -> "replay"
                })
                .putInt("seconds", seconds).putInt("threads", threads).putInt("repeats", repeats)
                .putString("wave", wave).putInt("total_len", totalLen)
                .putString("memory_mode", memoryMode)
                .putInt("core_ms", coreMs).putInt("overlap_ms", overlapMs).putInt("hop_ms", hopMs)
                .putBoolean("deadline_aware", deadlineAware).commit()
            editor.requestFocus()
            editor.postDelayed({ getSystemService(InputMethodManager::class.java)
                .showSoftInput(editor, InputMethodManager.SHOW_IMPLICIT) }, 500)
        } else {
            check(active == null) { "Run already active; force-stop between launches" }
            val connection = editor.onCreateInputConnection(android.view.inputmethod.EditorInfo())
            val log = BenchLog(this, id)
            active = BenchRun(this, log, BenchOptions(mode, seconds, threads, repeats, wave, totalLen, memoryMode,
                coreMs, overlapMs, hopMs, deadlineAware)) { text, final ->
                val ok = connection.setComposingText(text, 1)
                if (final) connection.finishComposingText()
                ok
            }
            Thread { active!!.run() }.start()
        }
    }
    override fun onDestroy() { active?.cancelled?.set(true); super.onDestroy() }
}
