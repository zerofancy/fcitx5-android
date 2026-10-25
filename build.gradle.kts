plugins {
    alias(libs.plugins.keyring)
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.aboutlibraries) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.kotlin.jvm) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kotlin.parcelize) apply false
}

keyring {
    secret("android_store_password", "signStorePassword", "SIGN_STORE_PASSWORD")
    secret("android_key_password", "signKeyPassword", "SIGN_KEY_PASSWORD")
}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}
