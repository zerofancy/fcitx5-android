package org.fcitx.voicep0

import android.content.Context
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.min

/** Fixed audio storage: no full-recording FloatArray and no dropping unprocessed segments. */
class AudioRing(val capacity: Int) {
    private val data = FloatArray(capacity)
    var written = 0L
        private set
    @Synchronized fun append(samples: FloatArray, offset: Int = 0, length: Int = samples.size) {
        repeat(length) { data[((written + it) % capacity).toInt()] = samples[offset + it] }
        written += length
    }
    @Synchronized fun count() = written
    @Synchronized fun snapshot(start: Long, end: Long): FloatArray {
        check(start >= maxOf(0, written - capacity)) { "Audio ring overrun: $start..$end, written=$written cap=$capacity" }
        check(end <= written && end >= start)
        return FloatArray((end - start).toInt()) { data[((start + it) % capacity).toInt()] }
    }
}

class WindowTrial(private val context: Context, private val log: BenchLog, private val options: BenchOptions,
                  private val cancelled: AtomicBoolean) {
    fun run(engine: Engine, source: FloatArray, trial: String,
            show: (String, Boolean, String, Double, Double) -> Unit) {
        val core = options.coreMs * 16L
        val overlap = options.overlapMs * 16L
        val total = options.seconds * 16000L
        val ring = AudioRing((core * 3 + overlap + 16000).toInt())
        val done = AtomicBoolean(false)
        val start = clockMs()
        val release = start + options.seconds * 1000.0
        log.event("trial_start", "trial" to trial, "start_ms" to start, "release_ms" to release,
            "audio_ring_capacity_samples" to ring.capacity, "core_ms" to options.coreMs,
            "overlap_ms" to options.overlapMs, "total_recording_cap" to false)
        val isMic = options.mode == "window-mic"
        val producer = Thread {
            if (isMic) {
                WindowMicrophone(context, log, ring, cancelled).capture(source, trial, start, release, done)
                return@Thread
            }
            try {
                val block = FloatArray(320)
                while (!cancelled.get() && ring.count() < total) {
                    val target = min(total, ((clockMs() - start) * 16).toLong())
                    while (ring.count() < target) {
                        val n = min(320L, target - ring.count()).toInt()
                        val position = ring.count()
                        repeat(n) { block[it] = source[((position + it) % source.size).toInt()] }
                        ring.append(block, length = n)
                    }
                    if (ring.count() < total) Thread.sleep(5)
                }
            } finally { done.set(true) }
        }.apply { name = "p0-audio-producer"; start() }
        var segment = 0L
        var fixed = ""
        var lastEnd = -1L
        var lastStart = -1L
        var lastText = ""
        var lastShown = ""
        var lastDecodeMs = 300.0
        var lastInputSize = 12800L
        try {
            while (!cancelled.get()) {
                val finished = done.get()
                val captured = ring.count()
                if (captured == 0L) { Thread.sleep(5); continue }
                val coreEnd = segment + core
                val end = min(captured, coreEnd)
                val closeSegment = captured >= coreEnd
                val final = (finished || (!isMic && captured == total)) && end == captured
                val left = maxOf(0, segment - overlap)
                if (finished && captured == segment && segment > 0) {
                    show(fixed, true, trial, start + captured / 16.0, start)
                    log.event("trial_end", "trial" to trial, "final_wait_ms" to clockMs() - release,
                        "audio_ring_capacity_samples" to ring.capacity, "total_samples" to captured)
                    break
                }
                if (!closeSegment && !final &&
                    (end - segment < min(12800L, core) || end - lastEnd < options.hopMs * 16L)) {
                    Thread.sleep(5); continue
                }
                if (options.deadlineAware && !closeSegment && !final) {
                    val estimated = lastDecodeMs * (end - left) / lastInputSize * 1.1
                    if (clockMs() + estimated > start + coreEnd / 16.0) {
                        Thread.sleep(5); continue
                    }
                }
                val kind = if (final) "final" else if (closeSegment) "segment" else "partial"
                val audioEnd = start + end / 16.0
                log.event("window", "trial" to trial, "kind" to kind, "left_sample" to left,
                    "core_start_sample" to segment, "end_sample" to end,
                    "captured_sample" to captured, "backlog_ms" to (captured - end) / 16.0)
                val decodeStart = clockMs()
                val reused = left == lastStart && end == lastEnd
                val text = if (reused) lastText else
                    engine.decode(ring.snapshot(left, end), kind, trial, audioEnd)
                if (!reused) {
                    lastDecodeMs = clockMs() - decodeStart
                    lastInputSize = end - left
                }
                lastStart = left; lastEnd = end; lastText = text
                val joined = if (segment == 0L) WindowMerge.Result(text, "first", 0, 0)
                    else WindowMerge.join(fixed, text, overlap != 0L)
                log.event("seam", "trial" to trial, "kind" to kind, "segment_sample" to segment,
                    "match" to joined.kind, "replaced_tokens" to joined.replaced,
                    "matched_tokens" to joined.matched, "window_text" to text)
                if (joined.text != lastShown || final) {
                    show(joined.text, final, trial, audioEnd, start)
                    lastShown = joined.text
                }
                if (final) {
                    log.event("trial_end", "trial" to trial, "final_wait_ms" to clockMs() - release,
                        "audio_ring_capacity_samples" to ring.capacity, "total_samples" to captured)
                    break
                }
                if (closeSegment) {
                    fixed = joined.text
                    segment = coreEnd
                }
            }
        } finally {
            if (!done.get()) cancelled.set(true)
            producer.join(2000)
            check(!producer.isAlive) { "Audio producer did not stop" }
        }
    }
}
