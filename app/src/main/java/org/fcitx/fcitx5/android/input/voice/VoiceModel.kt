/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */

package org.fcitx.fcitx5.android.input.voice

import android.content.Context
import org.json.JSONArray
import java.io.File
import java.security.MessageDigest

/** Versioned, verified private copy; never use credential-encrypted models before unlock. */
object VoiceModel {
    const val VERSION = "qwen3-0.6b-int8-68818b2"
    fun directory(context: Context) = File(context.noBackupFilesDir, VERSION)
    fun ready(context: Context) = runCatching {
        File(directory(context), ".ready").readText() == VERSION &&
            listOf("conv_frontend.onnx", "encoder.int8.onnx", "decoder.int8.onnx",
                "tokenizer/merges.txt", "tokenizer/vocab.json", "tokenizer/tokenizer_config.json")
                .all { File(directory(context), it).isFile }
    }.getOrDefault(false)

    @Synchronized fun prepare(context: Context, progress: (String) -> Unit) {
        if (ready(context)) return
        val dir = directory(context)
        val files = JSONArray(context.assets.open("voice/files.json").bufferedReader().use { it.readText() })
        check(files.length() == 6) { "Voice model is not bundled" }
        // Remove an incomplete previous preparation before calculating space for a fresh copy.
        check(!dir.exists() || dir.deleteRecursively()) { "Cannot clean incomplete model" }
        check(dir.mkdirs()) { "Cannot create model directory" }
        val bytes = (0 until files.length()).sumOf { files.getJSONObject(it).getLong("size") }
        check(dir.usableSpace >= bytes + 16L * 1024 * 1024) { "Not enough storage for voice model" }
        for (i in 0 until files.length()) {
            val entry = files.getJSONObject(i)
            val name = entry.getString("path")
            progress(name)
            val target = File(dir, name).apply { parentFile!!.mkdirs() }
            val temporary = File(target.path + ".tmp")
            val digest = MessageDigest.getInstance("SHA-256")
            try {
                context.assets.open("voice/$name").use { input ->
                    temporary.outputStream().buffered().use { output ->
                        val buffer = ByteArray(256 * 1024)
                        while (true) {
                            val n = input.read(buffer)
                            if (n < 0) break
                            digest.update(buffer, 0, n)
                            output.write(buffer, 0, n)
                        }
                    }
                }
                check(temporary.length() == entry.getLong("size")) { "Incomplete model: $name" }
                check(digest.digest().joinToString("") { "%02x".format(it) } == entry.getString("sha256")) {
                    "Invalid model: $name"
                }
                check(temporary.renameTo(target)) { "Cannot install model: $name" }
            } finally { temporary.delete() }
        }
        File(dir, ".ready").writeText(VERSION)
    }
}
