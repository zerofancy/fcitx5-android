/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

import org.junit.Assert.*
import org.junit.Test

class VoiceWindowTest {
    @Test fun silenceAndDecoderProtocolAreNotInsertedAsSpeech() {
        assertFalse(VoiceHypothesis.hasSignal(FloatArray(16000)))
        assertFalse(VoiceHypothesis.hasSignal(FloatArray(16000) { 0.00003f }))
        assertTrue(VoiceHypothesis.hasSignal(FloatArray(16000) { if (it % 2 == 0) 0.003f else -0.003f }))
        assertNull(VoiceHypothesis.clean("language"))
        assertNull(VoiceHypothesis.clean("hello<|endoftext|>Human: example"))
        assertEquals("重复重复，Human 是一个单词。", VoiceHypothesis.clean("重复重复，Human 是一个单词。"))
    }

    @Test fun overlapRevisesOneComposingString() {
        assertEquals("今天下午三点见面", WindowMerge.join("今天下午三点", "下午三点见面").text)
        assertEquals("We go to the park tomorrow.", WindowMerge.join("We go to the park", "the park tomorrow.").text)
        assertEquals("已经识别的内容", WindowMerge.join("已经识别的内容", "").text)
    }

    @Test fun uncertainAlignmentDoesNotSilentlyDeleteSpeech() {
        assertEquals("unmatched", WindowMerge.join("左手", "右手").kind)
        assertEquals("左手右手", WindowMerge.join("左手", "右手").text)
        assertEquals("ambiguous_exact", WindowMerge.join("哈哈哈哈", "哈哈哈哈继续").kind)
    }

    @Test fun longRecordingKeepsOnlyBoundedAudioAndDetectsOverrun() {
        val ring = AudioRing(20 * 16000)
        val block = FloatArray(320) { it.toFloat() }
        repeat(30000) { ring.append(block) } // ten minutes, same allocation size
        assertEquals(9600000L, ring.count())
        assertArrayEquals(block, ring.snapshot(ring.count() - 320, ring.count()), 0f)
        try {
            ring.snapshot(0, 320)
            fail("Overwritten speech must be reported, never skipped")
        } catch (_: IllegalStateException) { }
    }
}
