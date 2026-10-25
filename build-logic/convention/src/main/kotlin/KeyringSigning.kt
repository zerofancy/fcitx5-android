/*
 * SPDX-License-Identifier: LGPL-2.1-or-later
 * SPDX-FileCopyrightText: Copyright 2026 Fcitx5 for Android Contributors
 */
import com.android.build.api.dsl.ApkSigningConfig
import com.android.build.api.dsl.ApplicationExtension
import me.okonecny.gradlekeyring.PublicKeyringExtension
import org.gradle.api.GradleException
import org.gradle.api.NamedDomainObjectContainer
import org.gradle.api.Project
import java.security.KeyStore
import java.security.PrivateKey
import java.util.Properties

private fun Project.localSigningProperty(name: String): String? =
    providers.gradleProperty(name).orNull ?: Properties().run {
        rootProject.file("local.properties").takeIf { it.isFile }?.inputStream()?.use { load(it) }
        getProperty(name)
    }

val Project.keyringSigningEnabled: Boolean
    get() = localSigningProperty("keyringSigning")?.toBooleanStrictOrNull() ?: false

fun Project.registerSigningVerification() {
    tasks.register("verifyReleaseSigning") {
        group = "verification"
        description = "Checks the release keystore, alias and both passwords without building an APK."
        notCompatibleWithConfigurationCache("Reads local signing credentials")
        doLast {
            val config = this@registerSigningVerification.extensions.getByType(ApplicationExtension::class.java)
                .buildTypes.getByName("release").signingConfig
                ?: throw GradleException("Release signing is not configured.")
            val store = config.storeFile ?: throw GradleException("Signing keystore is not configured.")
            val storePassword = config.storePassword?.toCharArray()
                ?: throw GradleException("Keystore password is not configured.")
            val keyPassword = config.keyPassword?.toCharArray()
                ?: throw GradleException("Private key password is not configured.")
            try {
                val keystore = KeyStore.getInstance(store, storePassword)
                val alias = config.keyAlias ?: throw GradleException("Key alias is not configured.")
                if (keystore.getKey(alias, keyPassword) !is PrivateKey) {
                    throw GradleException("Alias '$alias' does not contain a private key.")
                }
                if (keystore.getCertificateChain(alias).isNullOrEmpty()) {
                    throw GradleException("Alias '$alias' does not contain a certificate chain.")
                }
                logger.lifecycle("Release signing verified: keystore, private key and certificate chain are readable.")
            } finally {
                storePassword.fill('\u0000')
                keyPassword.fill('\u0000')
            }
        }
    }
}

@Suppress("DEPRECATION") // Gradle still exposes the requested cache mode through StartParameter.
fun NamedDomainObjectContainer<out ApkSigningConfig>.fromKeyring(project: Project): ApkSigningConfig {
    if (project.gradle.startParameter.isConfigurationCacheRequested) {
        throw GradleException("Keyring signing requires --no-configuration-cache to avoid caching passwords.")
    }
    val path = project.localSigningProperty("keyringStoreFile")
        ?: throw GradleException("Set keyringStoreFile in local.properties before enabling keyringSigning.")
    val alias = project.localSigningProperty("keyringKeyAlias")?.takeIf { it.isNotBlank() }
        ?: throw GradleException("Set keyringKeyAlias in local.properties before enabling keyringSigning.")
    val keyFile = project.rootProject.file(path)
    if (!keyFile.isFile) throw GradleException("Signing keystore does not exist: $keyFile")
    val keyring = project.rootProject.extensions.getByType(PublicKeyringExtension::class.java)
    fun password(name: String): String = keyring.secrets[name]
        ?.takeUnless { it == "<not set>" }
        ?: throw GradleException(
            "Signing secret '$name' is unavailable. Initialize with " +
                "./gradlew -PkeyringSigning=false --no-configuration-cache :setSecretValue --name=$name"
        )
    val storePasswordValue = password("android_store_password")
    val keyPasswordValue = password("android_key_password")
    return maybeCreate("release").apply {
        storeFile = keyFile
        storePassword = storePasswordValue
        keyAlias = alias
        keyPassword = keyPasswordValue
    }
}
