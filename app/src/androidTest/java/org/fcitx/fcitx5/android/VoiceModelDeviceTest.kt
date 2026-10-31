/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android

import androidx.test.platform.app.InstrumentationRegistry
import org.fcitx.fcitx5.android.input.voice.VoiceModel
import org.junit.Assert.*
import org.junit.Test
import java.io.File

class VoiceModelDeviceTest {
    @Test fun bundledModelPreparesIntoPrivateStorage() {
        org.junit.Assume.assumeTrue(BuildConfig.VOICE_MODEL_BUNDLED)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        VoiceModel.prepare(context) { }
        assertTrue(VoiceModel.ready(context))
        assertEquals(755914231L, File(VoiceModel.directory(context), "decoder.int8.onnx").length())
        assertEquals(182491662L, File(VoiceModel.directory(context), "encoder.int8.onnx").length())
        // A second invocation must reuse the verified version, not rewrite a loaded model.
        val marker = File(VoiceModel.directory(context), ".ready").lastModified()
        VoiceModel.prepare(context) { fail("Model was unnecessarily unpacked twice") }
        assertEquals(marker, File(VoiceModel.directory(context), ".ready").lastModified())
    }
}
