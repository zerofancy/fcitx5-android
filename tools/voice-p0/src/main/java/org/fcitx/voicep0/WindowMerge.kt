package org.fcitx.voicep0

import java.util.Locale

/** Text-only overlap alignment. Confidence is logged; quality must be measured separately. */
object WindowMerge {
    data class Token(val value: String, val start: Int)
    data class Result(val text: String, val kind: String, val replaced: Int, val matched: Int)
    private val pattern = Regex("[\\p{IsHan}]|[\\p{L}\\p{N}]+")
    private fun tokens(s: String) = pattern.findAll(s).map {
        Token(it.value.lowercase(Locale.ROOT), it.range.first)
    }.toList()

    fun join(previous: String, incoming: String, overlap: Boolean = true): Result {
        if (previous.isBlank()) return Result(incoming.trim(), "first", 0, 0)
        if (incoming.isBlank()) return Result(previous, "empty", 0, 0)
        if (!overlap) return Result(concat(previous, incoming), "no_overlap", 0, 0)
        val a = tokens(previous).takeLast(48)
        val b = tokens(incoming).take(48)
        // Prefer the longest exact suffix/prefix; never deduplicate a single short token.
        val exact = (2..minOf(a.size, b.size)).filter { n ->
            a.takeLast(n).map { it.value } == b.take(n).map { it.value }
        }
        if (exact.isNotEmpty()) {
            val n = exact.last()
            return Result(concat(previous.substring(0, a[a.size - n].start), incoming),
                if (exact.size > 1) "ambiguous_exact" else "exact", n, n)
        }
        var best: Triple<Int, Int, Double>? = null
        for (n in 4..minOf(32, a.size)) {
            for (m in maxOf(4, n - 2)..minOf(b.size, n + 2)) {
                val x = a.takeLast(n).map { it.value }
                val y = b.take(m).map { it.value }
                val distance = editDistance(x, y)
                val ratio = distance.toDouble() / maxOf(n, m)
                if (ratio > .25 || x.last() != y.last()) continue
                val score = minOf(n, m) - distance * 2.0
                if (best == null || score > best.third) best = Triple(n, m, score)
            }
        }
        if (best != null) {
            val n = best.first
            return Result(concat(previous.substring(0, a[a.size - n].start), incoming), "fuzzy", n, best.second)
        }
        // Refuse to guess a deletion. An unmatched seam remains visible and is counted as a risk.
        return Result(concat(previous, incoming), "unmatched", 0, 0)
    }

    private fun concat(a: String, b: String): String {
        val left = a.trimEnd()
        val right = b.trimStart()
        val needsSpace = left.lastOrNull()?.let { it.isLetterOrDigit() && it.code < 128 } == true &&
            right.firstOrNull()?.let { it.isLetterOrDigit() && it.code < 128 } == true
        return left + (if (needsSpace) " " else "") + right
    }

    private fun editDistance(a: List<String>, b: List<String>): Int {
        var row = IntArray(b.size + 1) { it }
        for (i in a.indices) {
            val next = IntArray(b.size + 1)
            next[0] = i + 1
            for (j in b.indices) next[j + 1] = minOf(next[j] + 1, row[j + 1] + 1,
                row[j] + if (a[i] == b[j]) 0 else 1)
            row = next
        }
        return row[b.size]
    }
}
