package fr.tetenam.app

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.mutableStateOf
import androidx.core.content.ContextCompat

class MainActivity : ComponentActivity() {
    private lateinit var tete: Tete
    private val autorise = mutableStateOf(false)
    private var choixEnCours = false   // pendant le choix des fichiers, on garde la connexion

    private val permissions: Array<String> =
        if (Build.VERSION.SDK_INT >= 31)
            arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
        else
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

    private val demande = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        verifier()
    }

    private val choixFichiers = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) {
        choixEnCours = false
        tete.envoyerFichiers(it)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tete = Tete(applicationContext)
        setContent {
            Ecran(
                tete = tete,
                autorise = autorise.value,
                demanderAutorisation = { demande.launch(permissions) },
                choisirFichiers = {
                    choixEnCours = true
                    choixFichiers.launch(arrayOf("*/*"))
                },
            )
        }
    }

    private fun verifier() {
        autorise.value = permissions.all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
        if (autorise.value) tete.demarrer()
    }

    override fun onStart() {
        super.onStart()
        autorise.value = permissions.all {
            ContextCompat.checkSelfPermission(this, it) == PackageManager.PERMISSION_GRANTED
        }
        if (!autorise.value) {
            demande.launch(permissions)
            return
        }
        val bm = getSystemService(android.bluetooth.BluetoothManager::class.java)
        if (bm?.adapter?.isEnabled == false) {
            try {
                @Suppress("DEPRECATION")
                startActivityForResult(Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), 1)
            } catch (_: SecurityException) {
            }
        }
        tete.demarrer()
    }

    override fun onStop() {
        super.onStop()
        // Appli en arrière-plan : on libère la tête (et la batterie)
        if (!choixEnCours) tete.arreter()
    }
}
