package org.fcitx.voicep0

import android.content.Context
import android.os.Build
import android.os.Debug
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineQwen3AsrModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.min

fun clockMs() = SystemClock.elapsedRealtimeNanos() / 1e6

class BenchLog(val context: Context, val id: String) {
    private val file = File(context.getExternalFilesDir(null), "$id.jsonl")
    private val running = AtomicBoolean(false)
    private var sampler: Thread? = null
    @Synchronized fun event(type: String, vararg fields: Pair<String, Any>) {
        val obj = JSONObject().put("event", type).put("time_ms", clockMs())
        fields.forEach { obj.put(it.first, it.second) }
        file.appendText(obj.toString() + "\n")
        android.util.Log.i("VoiceP0", obj.toString())
    }
    fun memory(phase: String) {
        val status = File("/proc/self/status").readLines().mapNotNull {
            val p = it.split(':', limit = 2)
            if (p[0] in listOf("VmRSS", "VmHWM")) p[0] to p[1].trim().split(' ')[0].toLong() else null
        }.toMap()
        val info = Debug.MemoryInfo()
        Debug.getMemoryInfo(info)
        val power = context.getSystemService(PowerManager::class.java)
        event("memory", "phase" to phase, "rss_kib" to (status["VmRSS"] ?: -1),
            "hwm_kib" to (status["VmHWM"] ?: -1), "pss_kib" to info.totalPss,
            "native_heap_bytes" to Debug.getNativeHeapAllocatedSize(),
            "native_heap_size_bytes" to Debug.getNativeHeapSize(),
            "native_heap_free_bytes" to Debug.getNativeHeapFreeSize(),
            "thermal_status" to if (Build.VERSION.SDK_INT >= 29) power.currentThermalStatus else -1)
    }
    fun start() {
        event("device", "manufacturer" to Build.MANUFACTURER, "model" to Build.MODEL,
            "sdk" to Build.VERSION.SDK_INT, "abis" to Build.SUPPORTED_ABIS.joinToString(),
            "pid" to android.os.Process.myPid(), "runtime" to "sherpa-onnx-2.0.1",
            "sampling_period_ms" to 1000)
        memory("baseline")
        running.set(true)
        sampler = Thread {
            while (running.get()) {
                Thread.sleep(1000)
                if (running.get()) memory("periodic")
            }
        }.apply { start() }
    }
    fun stop() { running.set(false); sampler?.join(2000) }
}

class Engine(context: Context, private val log: BenchLog, threads: Int, totalLen: Int,
             memoryMode: String) : AutoCloseable {
    private val recognizer: OfflineRecognizer
    init {
        val dir = File(context.filesDir, "model")
        val provider = if (memoryMode == "default") "cpu" else {
            val config = File(context.filesDir, "cpu-$memoryMode.config")
            config.writeText(when (memoryMode) {
                "no-arena" -> "EnableCpuMemArena=0\nEnableMemPattern=0\n"
                "no-prepack" -> "SessionConfig.session.disable_prepacking=1\n"
                "compact" -> "EnableCpuMemArena=0\nEnableMemPattern=0\nSessionConfig.session.disable_prepacking=1\n"
                "basic" -> "EnableCpuMemArena=0\nEnableMemPattern=0\nGraphOptimizationLevel=1\n"
                else -> error("Unknown memory mode")
            })
            "cpu:${config.absolutePath}"
        }
        log.event("load_start", "threads" to threads, "max_total_len" to totalLen,
            "max_new_tokens" to 256, "memory_mode" to memoryMode, "provider" to provider)
        val start = clockMs()
        recognizer = OfflineRecognizer(config = OfflineRecognizerConfig(modelConfig = OfflineModelConfig(
            qwen3Asr = OfflineQwen3AsrModelConfig(
                convFrontend = "$dir/conv_frontend.onnx", encoder = "$dir/encoder.int8.onnx",
                decoder = "$dir/decoder.int8.onnx", tokenizer = "$dir/tokenizer",
                maxTotalLen = totalLen, maxNewTokens = 256),
            numThreads = threads, provider = provider, debug = false)))
        log.event("loaded", "load_ms" to clockMs() - start)
        log.memory("loaded")
    }
    fun decode(audio: FloatArray, kind: String, trial: String, audioEndMs: Double): String {
        val start = clockMs()
        log.event("decode_start", "trial" to trial, "kind" to kind,
            "samples" to audio.size, "audio_end_ms" to audioEndMs)
        val stream = recognizer.createStream()
        try {
            stream.acceptWaveform(audio, 16000)
            recognizer.decode(stream)
            val result = recognizer.getResult(stream).text
            log.event("decoded", "trial" to trial, "kind" to kind, "samples" to audio.size,
                "decode_ms" to clockMs() - start, "audio_end_ms" to audioEndMs, "text" to result)
            return result
        } finally { stream.release() }
    }
    override fun close() {
        recognizer.release()
        log.event("released")
        log.memory("released")
    }
}

fun readWave(file: File): FloatArray {
    val b = ByteBuffer.wrap(file.readBytes()).order(ByteOrder.LITTLE_ENDIAN)
    fun four(): String = ByteArray(4).also { b.get(it) }.toString(Charsets.US_ASCII)
    require(four() == "RIFF"); b.int; require(four() == "WAVE")
    var valid = false
    while (b.remaining() >= 8) {
        val name = four(); val length = b.int; val end = b.position() + length
        if (name == "fmt ") {
            require(b.short.toInt() == 1 && b.short.toInt() == 1)
            require(b.int == 16000); b.int; b.short; require(b.short.toInt() == 16)
            valid = true
        } else if (name == "data") {
            require(valid)
            return FloatArray(length / 2) { b.short / 32768f }
        }
        b.position(end + length % 2)
    }
    error("No PCM16 waveform: $file")
}

data class BenchOptions(val mode: String, val seconds: Int, val threads: Int, val repeats: Int,
                        val wave: String, val totalLen: Int = 512, val memoryMode: String = "default",
                        val coreMs: Int = 2000, val overlapMs: Int = 1000, val hopMs: Int = 500,
                        val deadlineAware: Boolean = false)

class BenchRun(private val context: Context, val log: BenchLog, private val options: BenchOptions,
               private val display: (String, Boolean) -> Boolean) {
    val cancelled = AtomicBoolean(false)
    private val main = Handler(Looper.getMainLooper())
    fun run() {
        log.start()
        try {
            if (options.mode.startsWith("window")) {
                WindowSelfCheck.run()
                log.event("window_selfcheck", "passed" to true)
            }
            val samples = readWave(File(context.filesDir, options.wave))
            log.event("config", "mode" to options.mode, "seconds" to options.seconds,
                "repeats" to options.repeats, "wave" to options.wave,
                "core_ms" to options.coreMs, "overlap_ms" to options.overlapMs, "hop_ms" to options.hopMs,
                "deadline_aware" to options.deadlineAware,
                "source_samples" to samples.size, "input_tiled" to (options.seconds * 16000 > samples.size))
            Engine(context, log, options.threads, options.totalLen, options.memoryMode).use { engine ->
                repeat(options.repeats) { trial ->
                    if (cancelled.get()) return@repeat
                    val id = "${options.mode}-${options.seconds}-$trial"
                    if (options.mode.startsWith("window")) {
                        WindowTrial(context, log, options, cancelled).run(engine, samples, id, ::show)
                    } else if (options.mode == "offline") {
                        val audio = FloatArray(options.seconds * 16000) { samples[it % samples.size] }
                        engine.decode(audio, "offline", id, 0.0)
                    } else if (options.mode == "mic") {
                        MicrophoneTrial(context, log, cancelled).run(engine, samples, options.seconds, id, ::show)
                    } else {
                        val audio = FloatArray(options.seconds * 16000) { samples[it % samples.size] }
                        replay(engine, audio, id)
                    }
                    log.memory("trial_end")
                }
            }
            System.gc()
            Thread.sleep(2000)
            log.memory("after_gc")
            log.event("complete", "cancelled" to cancelled.get())
        } catch (t: Throwable) {
            log.event("failure", "message" to t.toString(), "stack" to t.stackTraceToString())
        } finally { log.stop() }
    }
    private fun show(text: String, final: Boolean, trial: String, endMs: Double, startMs: Double) {
        val latch = CountDownLatch(1)
        main.post {
            try {
                val ok = !cancelled.get() && display(text, final)
                log.event("display", "trial" to trial, "kind" to if (final) "final" else "partial",
                    "ok" to ok, "audio_end_ms" to endMs, "since_start_ms" to clockMs() - startMs,
                    "age_ms" to clockMs() - endMs, "text" to text)
            } finally { latch.countDown() }
        }
        check(latch.await(5, TimeUnit.SECONDS)) { "UI blocked" }
    }
    private fun replay(engine: Engine, audio: FloatArray, trial: String) {
        val start = clockMs()
        val release = start + audio.size / 16.0
        log.event("trial_start", "trial" to trial, "start_ms" to start, "release_ms" to release)
        var lastCount = 0
        while (!cancelled.get()) {
            val now = clockMs()
            val count = min(audio.size, ((now - start) * 16).toInt())
            val final = now >= release
            if (!final && (count < 12800 || count - lastCount < 8000)) {
                Thread.sleep(10); continue
            }
            val end = start + count / 16.0
            val text = engine.decode(audio.copyOf(count), if (final) "final" else "partial", trial, end)
            show(text, final, trial, end, start)
            lastCount = count
            if (final) { log.event("trial_end", "trial" to trial, "final_wait_ms" to clockMs() - release); break }
        }
    }
}
