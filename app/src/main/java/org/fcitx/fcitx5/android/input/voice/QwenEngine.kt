/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

import android.content.Context
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineQwen3AsrModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig

/** Access only on the controller's serial worker, including release after cancellation. */
class QwenEngine(private val context: Context) : AutoCloseable {
    private var recognizer: OfflineRecognizer? = null
    fun get(): OfflineRecognizer {
        recognizer?.let { return it }
        val dir = VoiceModel.directory(context)
        return OfflineRecognizer(config = OfflineRecognizerConfig(modelConfig = OfflineModelConfig(
            qwen3Asr = OfflineQwen3AsrModelConfig(convFrontend = "$dir/conv_frontend.onnx",
                encoder = "$dir/encoder.int8.onnx", decoder = "$dir/decoder.int8.onnx",
                tokenizer = "$dir/tokenizer", maxTotalLen = 512, maxNewTokens = 256),
            numThreads = 2, provider = "cpu"))).also { recognizer = it }
    }
    override fun close() { recognizer?.release(); recognizer = null }
}
