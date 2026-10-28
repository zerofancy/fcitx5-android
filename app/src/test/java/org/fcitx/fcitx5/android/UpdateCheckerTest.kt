/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */
package org.fcitx.fcitx5.android

import org.fcitx.fcitx5.android.data.update.*
import org.junit.Assert.*
import org.junit.Test

class UpdateCheckerTest {
    private fun item(
        version: String = "10", software: String = "fcitx5-android", arch: String = "ARM64",
        url: String = "https://example.org/update.apk"
    ) = """{"software":"$software","os":"Android","arch":"$arch","packageType":"apk",
        "latest":{"versionCode":"$version","versionName":"v$version","distributionTitle":"Release",
        "packageType":"apk","downloadUrl":"$url","futureField":true}}"""

    private fun decode(items: String) = UpdateChecker.decode(
        200, """{"items":[$items],"futureField":true}""", "fcitx5-android", "ARM64"
    )

    @Test fun selectsFirstWithoutSortingOrParsingLaterItems() {
        assertEquals(10L, decode("${item()},${item("100")},null").versionCode)
        assertFalse(decode("${item("9")},${item("100")}").isNewerThan(10))
    }

    @Test fun invalidFirstDoesNotFallBack() {
        assertThrows(InvalidUpdateResponse::class.java) { decode("null,${item()}") }
        assertThrows(InvalidUpdateResponse::class.java) { decode("${item(arch = "X86_64")},${item()}") }
    }

    @Test fun comparesLongVersionsNumerically() {
        assertTrue(decode(item()).isNewerThan(9))
        assertFalse(decode(item()).isNewerThan(10))
        assertFalse(decode(item()).isNewerThan(11))
        assertEquals(Long.MAX_VALUE, decode(item(Long.MAX_VALUE.toString())).versionCode)
        assertTrue(decode(item("9007199254740993")).isNewerThan(9007199254740992L))
        listOf("0", "-1", "1.5", " 10", "+10", "9223372036854775808").forEach {
            assertThrows(InvalidUpdateResponse::class.java) { decode(item(it)) }
        }
    }

    @Test fun validatesResponseAndDownloadLink() {
        listOf("", "null", "{}", "<html>bad gateway</html>", """{"items":[]}""").forEach {
            assertThrows(InvalidUpdateResponse::class.java) {
                UpdateChecker.decode(200, it, "fcitx5-android", "ARM64")
            }
        }
        listOf("file:///tmp/update.apk", "intent://download", "javascript:alert(1)",
            "https:///missing-host", "/update.apk", "https://user:pass@example.org/app.apk").forEach {
            assertThrows(InvalidUpdateResponse::class.java) { decode(item(url = it)) }
        }
        assertEquals("http://example.org/update.apk", decode(item(url = "http://example.org/update.apk")).downloadUrl)
        assertThrows(InvalidUpdateResponse::class.java) { decode(item().replace("\"10\"", "10")) }
        assertThrows(InvalidUpdateResponse::class.java) { decode(item().replace("\"Android\"", "\"Linux\"")) }
        assertThrows(InvalidUpdateResponse::class.java) { decode(item().replace("\"apk\"", "\"zip\"")) }
    }

    @Test fun independentDebugAndReleaseQueries() {
        assertEquals("fcitx5-android", UpdateChecker.software(false))
        assertEquals("fcitx5-android-debug", UpdateChecker.software(true))
        assertEquals("https://zp.ntutn.top/api/v1/updates?software=fcitx5-android-debug&os=Android&arch=X86_64&packageType=apk",
            UpdateChecker.requestUrl(true, "X86_64"))
        val debug = item(software = "fcitx5-android-debug", arch = "X86_64")
        assertEquals(10L, UpdateChecker.decode(200, """{"items":[$debug]}""", "fcitx5-android-debug", "X86_64").versionCode)
        assertThrows(InvalidUpdateResponse::class.java) { decode(item(software = "fcitx5-android-debug")) }
        assertThrows(IllegalArgumentException::class.java) { UpdateChecker.requestUrl(false, "x86") }
    }

    @Test fun detectsInstalledArchitectureWithoutDeviceFallback() {
        assertEquals("ARM64", UpdateChecker.architecture("/data/app/pkg/lib/arm64"))
        assertEquals("X86_64", UpdateChecker.architecture("/data/app/pkg/lib/x86_64"))
        listOf("/data/app/pkg/lib/arm", "/data/app/pkg/lib/x86", "", "/unknown").forEach {
            assertNull(UpdateChecker.architecture(it))
        }
    }

    @Test fun serviceErrorsRemainFailures() {
        listOf(404 to "SOFTWARE_NOT_FOUND", 404 to "NO_MATCHING_PACKAGE", 409 to "AMBIGUOUS_LATEST",
            503 to "SERVICE_UNAVAILABLE", 429 to "RATE_LIMITED").forEach { (status, code) ->
            val error = assertThrows(UpdateServiceError::class.java) {
                UpdateChecker.decode(status, """{"error":{"code":"$code"}}""", "fcitx5-android", "ARM64")
            }
            assertEquals(status, error.status)
            assertEquals(code, error.code)
        }
        val error = assertThrows(UpdateServiceError::class.java) {
            UpdateChecker.decode(502, "<html>Bad gateway</html>", "fcitx5-android", "ARM64")
        }
        assertNull(error.code)
    }

    @Test fun readTimeoutRemainsNetworkFailure() {
        val stream = object : java.io.InputStream() {
            override fun read(): Int = throw java.net.SocketTimeoutException("Timed out")
        }
        assertThrows(java.net.SocketTimeoutException::class.java) { UpdateChecker.readBody(stream) }
    }

    @Test fun limitsResponseBytes() {
        val text = "更".repeat(20_000)
        assertEquals(text, UpdateChecker.readBody(text.byteInputStream()))
        assertThrows(InvalidUpdateResponse::class.java) {
            UpdateChecker.readBody("更".repeat(22_000).byteInputStream())
        }
    }
}
