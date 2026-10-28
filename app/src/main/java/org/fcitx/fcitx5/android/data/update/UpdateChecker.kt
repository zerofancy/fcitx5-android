/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */
package org.fcitx.fcitx5.android.data.update

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

data class AvailableUpdate(
    val versionCode: Long,
    val versionName: String,
    val distributionTitle: String,
    val downloadUrl: String
) {
    fun isNewerThan(installedVersion: Long) = versionCode > installedVersion
}

class InvalidUpdateResponse(cause: Throwable? = null) : Exception("Invalid update response", cause)
class UpdateServiceError(val status: Int, val code: String?) : Exception("Update service HTTP $status")

object UpdateChecker {
    private const val ENDPOINT = "https://zp.ntutn.top/api/v1/updates"
    private const val MAX_RESPONSE_BYTES = 65_536

    fun software(debug: Boolean) = if (debug) "fcitx5-android-debug" else "fcitx5-android"

    // Android's installed native library directory identifies the APK ABI, even
    // when a 64-bit device is running a 32-bit installation.
    fun architecture(nativeLibraryDir: String): String? = when (nativeLibraryDir.substringAfterLast('/')) {
        "arm64" -> "ARM64"
        "x86_64" -> "X86_64"
        else -> null
    }

    internal fun requestUrl(debug: Boolean, arch: String): String {
        require(arch == "ARM64" || arch == "X86_64")
        return "$ENDPOINT?software=${software(debug)}&os=Android&arch=$arch&packageType=apk"
    }

    suspend fun check(debug: Boolean, arch: String): AvailableUpdate = withContext(Dispatchers.IO) {
        val connection = URL(requestUrl(debug, arch)).openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 10_000
            connection.readTimeout = 10_000
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json")
            ensureActive()
            val status = connection.responseCode
            val body = (if (status == 200) connection.inputStream else connection.errorStream)
                ?.use { readBody(it) }.orEmpty()
            ensureActive()
            decode(status, body, software(debug), arch)
        } finally {
            connection.disconnect()
        }
    }

    internal fun readBody(stream: InputStream): String {
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (true) {
            val count = stream.read(buffer)
            if (count < 0) break
            if (output.size() + count > MAX_RESPONSE_BYTES) throw InvalidUpdateResponse()
            output.write(buffer, 0, count)
        }
        return output.toString("UTF-8")
    }

    internal fun decode(status: Int, body: String, software: String, arch: String): AvailableUpdate {
        if (status != 200) {
            val code = runCatching {
                Json.parseToJsonElement(body).jsonObject["error"]?.jsonObject
                    ?.get("code")?.jsonPrimitive?.content
            }.getOrNull()
            throw UpdateServiceError(status, code)
        }
        try {
            // Only the first result participates; later items need not have our schema.
            val item = Json.parseToJsonElement(body).jsonObject.getValue("items").jsonArray.first().jsonObject
            fun JsonObject.string(key: String): String {
                val value = getValue(key).jsonPrimitive
                require(value.isString)
                return value.content
            }
            require(item.string("software") == software && item.string("os") == "Android")
            require(item.string("arch") == arch && item.string("packageType") == "apk")
            val latest = item.getValue("latest").jsonObject
            require(latest.string("packageType") == "apk")
            val versionText = latest.string("versionCode")
            require(versionText.matches(Regex("[0-9]+")))
            val version = versionText.toLong()
            require(version > 0)
            val name = latest.string("versionName")
            require(name.isNotBlank())
            val downloadUrl = latest.string("downloadUrl")
            val uri = URI(downloadUrl)
            require(uri.scheme?.lowercase() in listOf("http", "https") && !uri.host.isNullOrBlank())
            require(uri.userInfo == null)
            return AvailableUpdate(version, name, latest.string("distributionTitle"), downloadUrl)
        } catch (e: Exception) {
            throw InvalidUpdateResponse(e)
        }
    }
}
