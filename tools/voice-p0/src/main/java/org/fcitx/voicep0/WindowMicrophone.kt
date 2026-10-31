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

/** Timed laboratory stimulus only. Real capture writes into the same fixed-capacity ring. */
class WindowMicrophone(private val context: Context, private val log: BenchLog,
                       private val ring: AudioRing, private val cancelled: AtomicBoolean) {
    @SuppressLint("MissingPermission")
    fun capture(source: FloatArray, trial: String, start: Double, release: Double, done: AtomicBoolean) {
        val manager = context.getSystemService(AudioManager::class.java)
        val oldVolume = manager.getStreamVolume(AudioManager.STREAM_MUSIC)
        val volume = maxOf(oldVolume, minOf(8, manager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)))
        var recorder: AudioRecord? = null
        var track: AudioTrack? = null
        var player: Thread? = null
        val playing = AtomicBoolean(true)
        var sumSquares = 0.0
        try {
            val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            check(minimum > 0)
            val record = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum * 2, 6400))
            recorder = record
            check(record.state == AudioRecord.STATE_INITIALIZED)
            val output = AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                .setAudioFormat(AudioFormat.Builder().setSampleRate(16000)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setTransferMode(AudioTrack.MODE_STREAM).setBufferSizeInBytes(6400).build()
            track = output
            output.setPreferredDevice(manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
                .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER })
            manager.setStreamVolume(AudioManager.STREAM_MUSIC, volume, 0)
            record.startRecording()
            check(record.recordingState == AudioRecord.RECORDSTATE_RECORDING)
            log.event("window_capture_start", "trial" to trial, "since_start_ms" to clockMs() - start,
                "original_media_volume" to oldVolume, "test_media_volume" to volume)
            player = Thread {
                val pcm = ShortArray(1600)
                var position = 0L
                try {
                    output.play()
                    log.event("audio_route", "trial" to trial, "output_type" to (output.routedDevice?.type ?: -1),
                        "input_type" to (record.routedDevice?.type ?: -1))
                    while (playing.get() && !cancelled.get() && clockMs() < release) {
                        repeat(pcm.size) { pcm[it] = (source[((position + it) % source.size).toInt()] * 24000).toInt().toShort() }
                        val n = output.write(pcm, 0, pcm.size)
                        if (n <= 0) break
                        position += n
                    }
                } catch (t: Throwable) {
                    log.event("failure", "message" to "Stimulus: $t")
                    cancelled.set(true)
                } finally { runCatching { output.stop() } }
            }.apply { name = "p0-window-stimulus"; start() }
            val pcm = ShortArray(320)
            val samples = FloatArray(320)
            while (!cancelled.get() && clockMs() < release) {
                val n = record.read(pcm, 0, pcm.size, AudioRecord.READ_NON_BLOCKING)
                check(n >= 0) { "AudioRecord.read=$n" }
                if (n == 0) { Thread.sleep(5); continue }
                repeat(n) { samples[it] = pcm[it] / 32768f; sumSquares += samples[it] * samples[it] }
                ring.append(samples, length = n)
            }
            record.stop()
            log.event("capture_stop", "trial" to trial, "after_release_ms" to clockMs() - release,
                "samples" to ring.count(), "rms" to kotlin.math.sqrt(sumSquares / maxOf(1L, ring.count())))
        } catch (t: Throwable) {
            cancelled.set(true)
            log.event("failure", "message" to "Microphone: $t", "stack" to t.stackTraceToString())
        } finally {
            playing.set(false)
            player?.join(2000)
            runCatching { recorder?.stop() }
            recorder?.release()
            if (player?.isAlive != true) track?.release()
            if (manager.getStreamVolume(AudioManager.STREAM_MUSIC) == volume)
                manager.setStreamVolume(AudioManager.STREAM_MUSIC, oldVolume, 0)
            done.set(true)
        }
    }
}
