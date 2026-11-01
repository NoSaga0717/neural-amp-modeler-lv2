package fr.tetenam.app

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import android.os.SystemClock
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.ArrayDeque
import java.util.UUID

// Mêmes UUID que tete-nam/ble.py sur le Pi
val UUID_SERVICE: UUID = UUID.fromString("7e7e0001-7465-7465-6e61-6d2d626c6531")
val UUID_COMMANDE: UUID = UUID.fromString("7e7e0002-7465-7465-6e61-6d2d626c6531")
val UUID_REPONSE: UUID = UUID.fromString("7e7e0003-7465-7465-6e61-6d2d626c6531")
val UUID_FICHIER: UUID = UUID.fromString("7e7e0004-7465-7465-6e61-6d2d626c6531")
val UUID_CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

data class Bloc(
    val id: Int, val nom: String, val chemin: String, val actif: Boolean,
    val mode: String, val q: Float, val entree: Float, val sortie: Float,
)

data class Etat(
    val service: String,
    val dsp: Double?,
    val xruns: Int,
    val temp: Double?,
    val throttled: String,
    val rate: Int,
    val period: Int,
    val nperiods: Int,
    val inputDbu: Double,
    val buffers: List<Int>,
    val blocs: List<Bloc>,
    val sig: String,
)

private fun JSONObject.doubleOuNull(k: String): Double? =
    if (isNull(k) || !has(k)) null else optDouble(k).takeIf { !it.isNaN() }

fun lireEtat(j: JSONObject): Etat {
    val r = j.getJSONObject("reglages")
    val b = j.getJSONArray("blocs")
    val blocs = (0 until b.length()).map {
        val o = b.getJSONObject(it)
        Bloc(o.getInt("id"), o.getString("nom"), o.optString("chemin"), o.getBoolean("actif"),
            o.optString("mode", "normalized"), o.optDouble("q", 0.0).toFloat(),
            o.optDouble("in", 0.0).toFloat(), o.optDouble("out", 0.0).toFloat())
    }
    val bu = j.optJSONArray("buffers") ?: JSONArray()
    return Etat(
        service = j.optString("service", "?"),
        dsp = j.doubleOuNull("dsp"),
        xruns = j.optInt("xruns"),
        temp = j.doubleOuNull("temp"),
        throttled = j.optString("throttled", "?"),
        rate = r.optInt("RATE", 48000),
        period = r.optInt("PERIOD", 256),
        nperiods = r.optInt("NPERIODS", 2),
        inputDbu = r.optDouble("INPUT_DBU", 16.0),
        buffers = (0 until bu.length()).map { bu.getInt(it) },
        blocs = blocs,
        sig = j.optString("sig"),
    )
}

/**
 * Lien Bluetooth Low Energy avec la tête : recherche, connexion, file
 * d'opérations GATT (Android n'en accepte qu'une à la fois), requêtes JSON
 * et interrogation de l'état toutes les secondes.
 */
@SuppressLint("MissingPermission")   // les permissions sont demandées par MainActivity
class Tete(private val ctx: Context) {
    // --- État affiché par l'interface ---
    var connexion by mutableStateOf("Bluetooth arrêté")
    var connecte by mutableStateOf(false)
    var etat by mutableStateOf<Etat?>(null)
    var disponibles by mutableStateOf<List<String>>(emptyList())
    val histo = mutableStateListOf<Double?>()
    var message by mutableStateOf("")
    var infoEnvoi by mutableStateOf("")
    var envoiEnCours by mutableStateOf(false)

    private val main = Handler(Looper.getMainLooper())
    private val bt = ctx.getSystemService(BluetoothManager::class.java)
    private var gatt: BluetoothGatt? = null
    private var recherche = false
    private var actif = false
    private var mtu = 23
    private val file = ArrayDeque<() -> Boolean>()
    private var occupe = false
    private val recu = ByteArrayOutputStream()
    private var numero = 0
    private val attentes = HashMap<Int, (JSONObject) -> Unit>()
    private var interrogation = 0L          // heure de la dernière demande d'état
    private var completDemande = true

    // ------------------------------------------------------------------ cycle

    fun demarrer() {
        if (actif) return
        actif = true
        chercher()
        main.post(tic)
    }

    fun arreter() {
        actif = false
        main.removeCallbacks(tic)
        arreterRecherche()
        gatt?.close()
        gatt = null
        connecte = false
        connexion = "Bluetooth arrêté"
    }

    private val tic = object : Runnable {
        override fun run() {
            if (!actif) return
            if (connecte && !envoiEnCours) interroger()
            main.postDelayed(this, 1000)
        }
    }

    // -------------------------------------------------------------- recherche

    private val rappelRecherche = object : ScanCallback() {
        override fun onScanResult(type: Int, r: ScanResult) {
            if (!recherche) return
            arreterRecherche()
            main.post { connecter(r.device) }
        }

        override fun onScanFailed(code: Int) {
            recherche = false
            connexion = "Recherche impossible (erreur $code)"
            main.postDelayed({ if (actif && !connecte) chercher() }, 3000)
        }
    }

    private fun chercher() {
        val adaptateur = bt?.adapter
        if (adaptateur == null || !adaptateur.isEnabled) {
            connexion = "Activez le Bluetooth du téléphone"
            main.postDelayed({ if (actif && !connecte) chercher() }, 2000)
            return
        }
        val scanner = adaptateur.bluetoothLeScanner ?: return
        connexion = "Recherche de la tête…"
        recherche = true
        val filtre = ScanFilter.Builder().setServiceUuid(ParcelUuid(UUID_SERVICE)).build()
        val reglages = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        try {
            scanner.startScan(listOf(filtre), reglages, rappelRecherche)
        } catch (e: SecurityException) {
            recherche = false
            connexion = "Autorisation Bluetooth refusée"
        }
    }

    private fun arreterRecherche() {
        if (!recherche) return
        recherche = false
        try {
            bt?.adapter?.bluetoothLeScanner?.stopScan(rappelRecherche)
        } catch (_: Exception) {
        }
    }

    private fun connecter(d: BluetoothDevice) {
        if (!actif) return
        connexion = "Connexion à ${d.name ?: "la tête"}…"
        gatt?.close()
        gatt = d.connectGatt(ctx, false, rappelGatt, BluetoothDevice.TRANSPORT_LE)
    }

    private fun perdu(texte: String) {
        connecte = false
        gatt?.close()
        gatt = null
        file.clear()
        occupe = false
        recu.reset()
        val enAttente = attentes.values.toList()
        attentes.clear()
        enAttente.forEach { it(JSONObject().put("ok", false).put("erreur", "Connexion perdue")) }
        envoiEnCours = false
        connexion = texte
        if (actif) main.postDelayed({ if (actif && !connecte && !recherche) chercher() }, 1500)
    }

    // ------------------------------------------------------------------- GATT

    private val rappelGatt = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, nouvel: Int) {
            main.post {
                if (g != gatt) return@post
                if (nouvel == BluetoothProfile.STATE_CONNECTED) {
                    connexion = "Connecté, préparation…"
                    g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                    if (!g.requestMtu(517)) g.discoverServices()
                } else {
                    perdu("Tête perdue, nouvelle recherche…")
                }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, m: Int, status: Int) {
            main.post {
                if (status == BluetoothGatt.GATT_SUCCESS) mtu = m
                g.discoverServices()
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            main.post {
                val c = g.getService(UUID_SERVICE)?.getCharacteristic(UUID_REPONSE)
                if (c == null) {
                    perdu("Service Tête NAM introuvable sur cet appareil")
                    return@post
                }
                g.setCharacteristicNotification(c, true)
                val d = c.getDescriptor(UUID_CCCD)
                if (d == null) {
                    perdu("Notifications indisponibles sur la tête")
                    return@post
                }
                val v = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                if (Build.VERSION.SDK_INT >= 33) {
                    g.writeDescriptor(d, v)
                } else {
                    @Suppress("DEPRECATION")
                    d.value = v
                    @Suppress("DEPRECATION")
                    g.writeDescriptor(d)
                }
            }
        }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) {
            main.post {
                connecte = true
                connexion = "Connecté"
                message = ""
                completDemande = true
                interrogation = 0
                demander(JSONObject().put("op", "bonjour").put("mtu", mtu)) { }
                interroger()
            }
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            main.post {
                occupe = false
                suivant()
            }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, valeur: ByteArray) {
            val copie = valeur.copyOf()
            main.post { recevoir(copie) }
        }

        @Deprecated("Android 12 et moins")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            if (Build.VERSION.SDK_INT >= 33) return
            @Suppress("DEPRECATION")
            val copie = c.value?.copyOf() ?: return
            main.post { recevoir(copie) }
        }
    }

    /** Ajoute une écriture à la file ; elles partent une par une. */
    private fun ecrire(uuid: UUID, octets: ByteArray) {
        file.add {
            val g = gatt ?: return@add false
            val c = g.getService(UUID_SERVICE)?.getCharacteristic(uuid) ?: return@add false
            val type = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            if (Build.VERSION.SDK_INT >= 33) {
                g.writeCharacteristic(c, octets, type) == BluetoothGatt.GATT_SUCCESS
            } else {
                @Suppress("DEPRECATION")
                c.writeType = type
                @Suppress("DEPRECATION")
                c.value = octets
                @Suppress("DEPRECATION")
                g.writeCharacteristic(c)
            }
        }
        suivant()
    }

    private fun suivant() {
        while (!occupe && file.isNotEmpty()) {
            val op = file.poll() ?: return
            if (op()) occupe = true
        }
    }

    private fun morceaux(octets: ByteArray): List<ByteArray> {
        val taille = maxOf(20, mtu - 3)
        return (octets.indices step taille).map { octets.copyOfRange(it, minOf(it + taille, octets.size)) }
    }

    // ------------------------------------------------------ requêtes JSON

    private fun demander(d: JSONObject, delai: Long = 20000, rappel: (JSONObject) -> Unit) {
        if (!connecte) {
            rappel(JSONObject().put("ok", false).put("erreur", "Pas connecté à la tête"))
            return
        }
        val n = ++numero
        attentes[n] = rappel
        d.put("n", n)
        morceaux((d.toString() + "\n").toByteArray()).forEach { ecrire(UUID_COMMANDE, it) }
        // Pas de réponse à temps : on abandonne cette demande
        main.postDelayed({
            attentes.remove(n)?.invoke(JSONObject().put("ok", false).put("erreur", "La tête ne répond pas"))
        }, delai)
    }

    private fun recevoir(octets: ByteArray) {
        for (b in octets) {
            if (b == '\n'.code.toByte()) {
                val texte = recu.toString(Charsets.UTF_8.name())
                recu.reset()
                try {
                    val j = JSONObject(texte)
                    attentes.remove(j.optInt("n", -1))?.invoke(j)
                } catch (_: Exception) {
                }
            } else {
                recu.write(b.toInt())
            }
        }
    }

    private fun interroger() {
        val maintenant = SystemClock.elapsedRealtime()
        if (maintenant - interrogation < 4000 && interrogation != 0L) return   // une à la fois
        interrogation = maintenant
        val complet = completDemande
        demander(JSONObject().put("op", "etat").put("leger", !complet)) { j ->
            interrogation = 0
            if (!j.has("blocs")) {
                if (j.has("erreur")) message = j.optString("erreur")
                return@demander
            }
            try {
                val e = lireEtat(j)
                if (complet) {
                    val d = j.optJSONArray("disponibles") ?: JSONArray()
                    disponibles = (0 until d.length()).map { d.getString(it) }
                    val h = j.optJSONArray("histo") ?: JSONArray()
                    histo.clear()
                    for (i in 0 until h.length()) histo.add(if (h.isNull(i)) null else h.optDouble(i))
                    completDemande = false
                } else {
                    histo.add(e.dsp)
                    while (histo.size > 120) histo.removeAt(0)
                    if (e.sig != etat?.sig) completDemande = true   // la liste des modèles a changé
                }
                etat = e
            } catch (ex: Exception) {
                message = "Réponse illisible : ${ex.message}"
            }
        }
    }

    /** Envoie un réglage (même format que la page web) puis relit l'état. */
    fun regler(op: String, params: JSONObject) {
        params.put("op", op)
        demander(params) { r ->
            message = if (r.optBoolean("ok")) "" else r.optString("erreur", r.optString("reponse", "Erreur"))
            interrogation = 0
            interroger()
        }
    }

    // ---------------------------------------------------- envoi de fichiers

    fun envoyerFichiers(uris: List<Uri>) {
        if (uris.isEmpty() || envoiEnCours) return
        envoiEnCours = true
        val lignes = mutableListOf<String>()
        fun un(i: Int) {
            if (i >= uris.size || !connecte) {
                envoiEnCours = false
                infoEnvoi = lignes.joinToString("\n")
                completDemande = true
                interrogation = 0
                interroger()
                return
            }
            val uri = uris[i]
            val nom = nomFichier(uri)
            val octets = try {
                ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            } catch (e: Exception) {
                null
            }
            if (octets == null) {
                lignes.add("✗ $nom : lecture impossible")
                un(i + 1)
                return
            }
            infoEnvoi = (lignes + "Envoi ${i + 1}/${uris.size} : $nom…").joinToString("\n")
            demander(JSONObject().put("op", "envoi_debut").put("nom", nom)) { r ->
                if (!r.optBoolean("ok")) {
                    lignes.add("✗ $nom : ${r.optString("erreur")}")
                    un(i + 1)
                    return@demander
                }
                val parts = morceaux(octets)
                var faits = 0
                parts.forEach { p ->
                    ecrire(UUID_FICHIER, p)
                    file.add {
                        // Pseudo-opération : met à jour la progression sans rien envoyer
                        faits++
                        if (faits % 20 == 0 || faits == parts.size) {
                            infoEnvoi = (lignes + "Envoi ${i + 1}/${uris.size} : $nom " +
                                "(${faits * 100 / parts.size} %)").joinToString("\n")
                        }
                        false
                    }
                }
                demander(JSONObject().put("op", "envoi_fin").put("taille", octets.size), 15 * 60 * 1000L) { f ->
                    lignes.add(
                        if (f.optBoolean("ok")) "✓ ${f.optString("nom", nom)}" +
                            (if (f.optBoolean("remplace")) " (remplacé)" else "")
                        else "✗ $nom : ${f.optString("erreur")}"
                    )
                    un(i + 1)
                }
            }
        }
        un(0)
    }

    private fun nomFichier(uri: Uri): String {
        ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
            if (it.moveToFirst()) return it.getString(0)
        }
        return uri.lastPathSegment ?: "modele.nam"
    }
}
