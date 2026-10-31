/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import java.util.concurrent.atomic.AtomicBoolean

/** One capture producer, one serial native decoder. JNI is never freed by the UI thread. */
class VoiceSession {
    private val stopping = AtomicBoolean(false)
    private val cancelled = AtomicBoolean(false)
    private val done = AtomicBoolean(false)
    private val ring = AudioRing(20 * 16000) // 3 * core + overlap + 1 s; independent of total duration
    @Volatile private var recorder: AudioRecord? = null
    @Volatile private var captureError: Throwable? = null
    fun stop() {
        stopping.set(true)
        // stop() unblocks READ_BLOCKING; the producer owns release().
        runCatching { recorder?.stop() }
    }
    fun cancel() { cancelled.set(true); stop() }

    @SuppressLint("MissingPermission")
    fun run(acquire: () -> OfflineRecognizer, started: () -> Unit, loaded: () -> Unit, show: (String) -> Unit) {
        val min = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        check(min > 0) { "Microphone format unavailable" }
        val record = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(min * 2, 6400))
        recorder = record
        var producer: Thread? = null
        try {
            check(record.state == AudioRecord.STATE_INITIALIZED) { "Microphone unavailable" }
            if (stopping.get()) return
            record.startRecording()
            check(record.recordingState == AudioRecord.RECORDSTATE_RECORDING) { "Microphone did not start" }
            started()
            producer = Thread {
                try {
                    val pcm = ShortArray(320)
                    val floats = FloatArray(320)
                    var blocks = 0
                    while (!stopping.get()) {
                        val n = record.read(pcm, 0, pcm.size)
                        if (stopping.get()) break
                        check(n > 0) { "Microphone read failed ($n)" }
                        if (++blocks % 50 == 1 && android.os.Build.VERSION.SDK_INT >= 29) {
                            check(record.activeRecordingConfiguration?.isClientSilenced != true) {
                                "Microphone silenced by system"
                            }
                        }
                        repeat(n) { floats[it] = pcm[it] / 32768f }
                        ring.append(floats, length = n)
                    }
                } catch (e: Throwable) { if (!stopping.get()) captureError = e }
                finally {
                    if (captureError != null) stop()
                    done.set(true)
                }
            }.apply { name = "voice-capture"; start() }
            val engine = acquire()
            loaded()
            var segment = 0L
            var fixed = ""
            var lastStart = -1L
            var lastEnd = -1L
            var lastText = ""
            while (!cancelled.get()) {
                captureError?.let { throw it }
                val finished = done.get()
                val captured = ring.count()
                if (finished && captured == segment) break
                val end = minOf(captured, segment + 96000L)
                val close = end == segment + 96000L
                val final = finished && end == captured
                if (end == 0L || (!close && !final &&
                        (end - segment < 12800 || end - lastEnd < 8000))) {
                    Thread.sleep(10); continue
                }
                val left = maxOf(0, segment - 16000)
                if (left != lastStart || end != lastEnd) {
                    val audio = ring.snapshot(left, end)
                    val stream = engine.createStream()
                    val previousText = if (left == lastStart) lastText else ""
                    try {
                        if (VoiceHypothesis.hasSignal(audio)) {
                            stream.acceptWaveform(audio, 16000)
                            engine.decode(stream)
                            val raw = engine.getResult(stream).text.trim()
                            lastText = VoiceHypothesis.clean(raw) ?: previousText
                        } else lastText = ""
                    } finally { stream.release() }
                    lastStart = left; lastEnd = end
                }
                if (cancelled.get()) break
                val joined = if (segment == 0L) lastText else WindowMerge.join(fixed, lastText).text
                show(joined)
                if (final) break
                if (close) { fixed = joined; segment += 96000 }
            }
        } finally {
            stop()
            producer?.join() // read is unblocked above; no native/capture resources outlive this worker
            recorder = null
            record.release()
        }
    }
}
