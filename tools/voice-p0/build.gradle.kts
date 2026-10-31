buildscript {
    repositories { google(); mavenCentral() }
    dependencies { classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.10") }
}
plugins { id("com.android.application") version "9.4.1" }

android {
    namespace = "org.fcitx.voicep0"
    compileSdk = 36
    defaultConfig {
        applicationId = "org.fcitx.voicep0"
        minSdk = 23
        targetSdk = 36
        versionCode = 1
        versionName = "p0-1"
        ndk { abiFilters += "arm64-v8a" }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(files(System.getProperty("user.home") +
        "/.cache/fcitx5-voice-p0/sherpa-onnx-2.0.1.aar"))
}
