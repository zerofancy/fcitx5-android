/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

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
