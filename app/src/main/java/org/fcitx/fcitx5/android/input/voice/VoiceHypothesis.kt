/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

/** Conservative digital-silence gate, not a general speech/noise classifier. */
object VoiceHypothesis {
    fun hasSignal(audio: FloatArray): Boolean {
        if (audio.isEmpty()) return false
        var power = 0.0
        var peak = 0f
        for (value in audio) {
            power += value * value
            peak = maxOf(peak, kotlin.math.abs(value))
        }
        return power / audio.size >= 0.0003 * 0.0003 && peak >= 0.001f
    }

    /** Invalid decoder protocol output must never be inserted into the host editor. */
    fun clean(text: String): String? = when {
        text.equals("language", ignoreCase = true) || text.contains("<|") || text.contains("|>") -> null
        else -> text
    }
}
