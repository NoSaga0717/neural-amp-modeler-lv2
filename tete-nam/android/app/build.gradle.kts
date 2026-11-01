plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "fr.tetenam.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.tetenam.app"
        minSdk = 26
        targetSdk = 35
        // La CI passe le numéro de build : chaque APK peut s'installer par-dessus le précédent
        versionCode = (System.getenv("NUMERO_BUILD") ?: "1").toInt()
        versionName = "0.1." + (System.getenv("NUMERO_BUILD") ?: "0")
    }

    signingConfigs {
        // Clé fixe rangée dans le dépôt (appli perso, pas de Play Store) :
        // les mises à jour s'installent sans désinstaller l'ancienne version.
        create("tete") {
            storeFile = file("tete-nam.keystore")
            storePassword = "tetenam"
            keyAlias = "tetenam"
            keyPassword = "tetenam"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("tete")
        }
        debug {
            signingConfig = signingConfigs.getByName("tete")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    val bom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(bom)
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.core:core-ktx:1.15.0")
}
