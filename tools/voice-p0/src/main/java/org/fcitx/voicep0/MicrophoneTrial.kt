package org.fcitx.voicep0

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.min
import kotlin.math.sqrt

/** Acoustic loopback: play a known fixture on the phone speaker and capture the real mic. */
class MicrophoneTrial(private val context: Context, private val log: BenchLog,
                      private val cancelled: AtomicBoolean) {
    @SuppressLint("MissingPermission")
    fun run(engine: Engine, source: FloatArray, seconds: Int, trial: String,
            show: (String, Boolean, String, Double, Double) -> Unit) {
        val minBytes = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT)
        require(minBytes > 0)
        val record = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minBytes * 2, 6400))
        check(record.state == AudioRecord.STATE_INITIALIZED)
        val playback = AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(16000)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
            .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(6400).build()
        val audioManager = context.getSystemService(AudioManager::class.java)
        val previousVolume = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
        val stimulusVolume = maxOf(previousVolume, minOf(8, audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)))
        playback.setPreferredDevice(audioManager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER })
        val lock = Any()
        val buffer = FloatArray(seconds * 16000 + 16000)
        var count = 0
        var readEnd = 0.0
        val capturing = AtomicBoolean(true)
        var capture: Thread? = null
        var player: Thread? = null
        val start = clockMs()
        val release = start + seconds * 1000.0
        try {
            audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, stimulusVolume, 0)
            record.startRecording()
            check(record.recordingState == AudioRecord.RECORDSTATE_RECORDING)
            log.event("capture_start", "trial" to trial, "start_ms" to start, "release_ms" to release,
                "audio_source" to "VOICE_RECOGNITION", "sample_rate" to record.sampleRate,
                "original_media_volume" to previousVolume, "test_media_volume" to stimulusVolume,
                "stimulus" to "same-device speaker acoustic loopback; not human speech")
            capture = Thread {
                val chunk = ShortArray(320)
                try {
                    while (capturing.get() && !cancelled.get() && clockMs() < release) {
                        val n = record.read(chunk, 0, chunk.size, AudioRecord.READ_NON_BLOCKING)
                        if (n < 0) error("AudioRecord.read=$n")
                        if (n == 0) { Thread.sleep(5); continue }
                        synchronized(lock) {
                            val take = min(n, buffer.size - count)
                            repeat(take) { buffer[count + it] = chunk[it] / 32768f }
                            count += take
                            readEnd = clockMs()
                        }
                    }
                } catch (t: Throwable) {
                    log.event("capture_failure", "trial" to trial, "error" to t.toString())
                    cancelled.set(true)
                } finally {
                    record.stop()
                    log.event("capture_stop", "trial" to trial, "after_release_ms" to clockMs() - release,
                        "samples" to count)
                }
            }.apply { start() }
            player = Thread {
                val pcm = ShortArray(1600)
                var position = 0
                try {
                    playback.play()
                    log.event("audio_route", "trial" to trial,
                        "output_type" to (playback.routedDevice?.type ?: -1),
                        "input_type" to (record.routedDevice?.type ?: -1))
                    while (capturing.get() && !cancelled.get() && clockMs() < release) {
                        repeat(pcm.size) { pcm[it] = (source[(position + it) % source.size] * 24000).toInt().toShort() }
                        val n = playback.write(pcm, 0, pcm.size)
                        if (n <= 0) break
                        position += n
                    }
                } finally { playback.stop() }
            }.apply { start() }
            var lastCount = 0
            while (!cancelled.get()) {
                val final = clockMs() >= release
                if (final) {
                    capturing.set(false)
                    capture.join(2000)
                    check(!capture.isAlive) { "Capture failed to stop" }
                }
                val snapshot = synchronized(lock) {
                    if (!final && (count < 12800 || count - lastCount < 8000)) null
                    else buffer.copyOf(count) to readEnd
                }
                if (snapshot == null) { Thread.sleep(10); continue }
                if (snapshot.first.isEmpty()) error("No mic samples")
                val text = engine.decode(snapshot.first, if (final) "final" else "partial", trial, snapshot.second)
                show(text, final, trial, snapshot.second, start)
                lastCount = snapshot.first.size
                if (final) {
                    val rms = sqrt(snapshot.first.sumOf { (it * it).toDouble() } / snapshot.first.size)
                    log.event("trial_end", "trial" to trial, "final_wait_ms" to clockMs() - release,
                        "captured_seconds" to snapshot.first.size / 16000.0, "rms" to rms)
                    break
                }
            }
        } finally {
            capturing.set(false)
            capture?.join(2000)
            player?.join(2000)
            if (capture?.isAlive != true) record.release()
            if (player?.isAlive != true) playback.release()
            if (audioManager.getStreamVolume(AudioManager.STREAM_MUSIC) == stimulusVolume) {
                audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, previousVolume, 0)
            }
        }
    }
}
