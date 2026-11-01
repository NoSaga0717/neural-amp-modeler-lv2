package fr.tetenam.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.util.Locale

// Mêmes couleurs que la page web
private val FOND = Color(0xFF141414)
private val CARTE = Color(0xFF1F1F1F)
private val TEXTE = Color(0xFFEEEEEE)
private val DOUX = Color(0xFF999999)
private val OK = Color(0xFF4CAF50)
private val MOYEN = Color(0xFFE0A800)
private val MAL = Color(0xFFE5484D)
private val ACCENT = Color(0xFFD9822B)

private fun couleur(v: Double?, a: Double, b: Double) =
    when {
        v == null -> TEXTE
        v < a -> OK
        v < b -> MOYEN
        else -> MAL
    }

private fun nom(chemin: String) = chemin.substringAfterLast('/')
private fun f1(v: Double) = String.format(Locale.FRANCE, "%.1f", v)
private fun nombre(v: Float) = if (v == v.toInt().toFloat()) v.toInt().toString() else
    String.format(Locale.US, "%.2f", v).trimEnd('0').trimEnd('.')

@Composable
fun Ecran(tete: Tete, autorise: Boolean, demanderAutorisation: () -> Unit, choisirFichiers: () -> Unit) {
    MaterialTheme(colorScheme = darkColorScheme(primary = ACCENT, background = FOND, surface = CARTE)) {
        Column(
            Modifier
                .fillMaxSize()
                .background(FOND)
                .safeDrawingPadding()
                .verticalScroll(rememberScrollState())
                .padding(16.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Tête NAM", color = TEXTE, fontSize = 22.sp, fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f))
                val e = tete.etat
                val (txt, fond) = when {
                    !tete.connecte -> "Bluetooth" to Color(0xFF333333)
                    e == null -> "…" to Color(0xFF333333)
                    e.service == "active" -> "active" to OK
                    else -> e.service to MAL
                }
                Text(txt, color = if (fond == OK) Color.Black else TEXTE, fontSize = 13.sp,
                    modifier = Modifier.background(fond, RoundedCornerShape(12.dp)).padding(horizontal = 10.dp, vertical = 3.dp))
            }
            Text(tete.connexion, color = if (tete.connecte) DOUX else MOYEN, fontSize = 13.sp)
            if (!autorise) {
                Spacer(Modifier.height(12.dp))
                Text("L'appli a besoin de l'autorisation Bluetooth (appareils à proximité) pour trouver la tête.",
                    color = TEXTE)
                Button(onClick = demanderAutorisation, modifier = Modifier.padding(top = 8.dp)) {
                    Text("Autoriser")
                }
            }
            val e = tete.etat
            if (e != null) {
                Mesures(e, tete.histo)
                Titre("Réglages audio")
                ReglagesAudio(e, tete)
                Titre("Chaîne (entrée → Pédale → Ampli → power amp)")
                e.blocs.forEach { BlocCarte(it, tete.disponibles, tete) }
            }
            Titre("Fichiers")
            OutlinedButton(
                onClick = choisirFichiers, enabled = tete.connecte && !tete.envoiEnCours,
                modifier = Modifier.fillMaxWidth().padding(top = 10.dp)
            ) { Text("Envoyer des fichiers .nam vers la tête", color = TEXTE) }
            if (tete.infoEnvoi.isNotEmpty()) Text(tete.infoEnvoi, color = DOUX, fontSize = 13.sp,
                modifier = Modifier.padding(top = 6.dp))
            if (tete.message.isNotEmpty()) Text(tete.message, color = MAL, fontSize = 13.sp,
                modifier = Modifier.padding(top = 8.dp))
            Text("Chaque réglage est appliqué tout de suite et sauvegardé sur la tête, comme depuis la page web. " +
                "L'envoi de fichiers en Bluetooth est lent (environ une minute par Mo).",
                color = DOUX, fontSize = 12.sp, modifier = Modifier.padding(top = 16.dp))
        }
    }
}

@Composable
private fun Titre(t: String) =
    Text(t, color = DOUX, fontSize = 15.sp, modifier = Modifier.padding(top = 20.dp))

@Composable
private fun Carte(modifier: Modifier = Modifier, contenu: @Composable () -> Unit) {
    Column(modifier.padding(top = 10.dp).fillMaxWidth().background(CARTE, RoundedCornerShape(10.dp)).padding(12.dp)) {
        contenu()
    }
}

@Composable
private fun Valeur(titre: String, valeur: String, c: Color, modifier: Modifier, taille: Int = 30) {
    Carte(modifier) {
        Text(titre, color = DOUX, fontSize = 13.sp)
        Text(valeur, color = c, fontSize = taille.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun Mesures(e: Etat, histo: List<Double?>) {
    Carte {
        Text("Charge DSP", color = DOUX, fontSize = 13.sp)
        Text(e.dsp?.let { f1(it) + " %" } ?: "–", color = couleur(e.dsp, 70.0, 85.0),
            fontSize = 30.sp, fontWeight = FontWeight.SemiBold)
        Canvas(Modifier.fillMaxWidth().height(70.dp).padding(top = 6.dp)) {
            val w = size.width
            val h = size.height
            listOf(70f, 85f).forEach {
                val y = h - it / 100f * h
                drawLine(Color(0xFF333333), Offset(0f, y), Offset(w, y), 2f)
            }
            val p = Path()
            var premier = true
            histo.forEachIndexed { i, v ->
                if (v == null) return@forEachIndexed
                val x = i / 119f * w
                val y = h - (minOf(v, 100.0) / 100.0).toFloat() * h
                if (premier) p.moveTo(x, y) else p.lineTo(x, y)
                premier = false
            }
            drawPath(p, ACCENT, style = Stroke(width = 4f))
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Valeur("Xruns (craquements)", e.xruns.toString(), if (e.xruns > 0) MAL else OK, Modifier.weight(1f))
        Valeur("Température", e.temp?.let { "${it.toInt()} °C" } ?: "–", couleur(e.temp, 70.0, 80.0),
            Modifier.weight(1f))
    }
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        val ok = e.throttled == "0x0"
        Valeur("Throttling", if (ok) "aucun" else e.throttled, if (ok) OK else MAL, Modifier.weight(1f), 20)
        Valeur("Audio", "${e.rate / 1000} kHz, ${e.period} × ${e.nperiods}\nentrée ${nombre(e.inputDbu.toFloat())} dBu",
            TEXTE, Modifier.weight(1f), 14)
    }
}

@Composable
private fun Choix(texte: String, options: List<Pair<String, String>>, actif: Boolean = true,
                  modifier: Modifier = Modifier.fillMaxWidth(), choisir: (String) -> Unit) {
    var ouvert by remember { mutableStateOf(false) }
    Box(modifier.padding(top = 6.dp)) {
        OutlinedButton(onClick = { ouvert = true }, enabled = actif, modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(6.dp)) {
            Text(texte, color = TEXTE, modifier = Modifier.weight(1f), maxLines = 1)
            Text("▾", color = DOUX)
        }
        DropdownMenu(expanded = ouvert, onDismissRequest = { ouvert = false }) {
            options.forEach { (valeur, libelle) ->
                DropdownMenuItem(text = { Text(libelle) }, onClick = {
                    ouvert = false
                    choisir(valeur)
                })
            }
        }
    }
}

@Composable
private fun ReglagesAudio(e: Etat, tete: Tete) {
    var buffer by remember(e.period) { mutableStateOf(e.period) }
    var confirmer by remember { mutableStateOf(false) }
    var cal by remember(e.inputDbu) { mutableStateOf(nombre(e.inputDbu.toFloat())) }
    val ms = { t: Int -> f1(t * 2.0 / e.rate * 1000) }
    Carte {
        Etiquette("Buffer JACK (2 périodes)", "actuel : ${e.period} × ${e.nperiods} ≈ ${f1(e.period * e.nperiods.toDouble() / e.rate * 1000)} ms")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Choix("$buffer (≈ ${ms(buffer)} ms)", e.buffers.map { it.toString() to "$it (≈ ${ms(it)} ms)" },
                modifier = Modifier.weight(1f)) { buffer = it.toInt() }
            Spacer(Modifier.width(8.dp))
            Button(onClick = { confirmer = true }, modifier = Modifier.padding(top = 6.dp)) { Text("Appliquer") }
        }
        Etiquette("Calibration d'entrée (dBu pour 0 dBFS, M4 : 16)", "actuel : ${nombre(e.inputDbu.toFloat())} dBu")
        Row(verticalAlignment = Alignment.CenterVertically) {
            val envoyer = {
                val v = cal.replace(',', '.').toDoubleOrNull()
                if (v == null) tete.message = "Calibration : nombre attendu"
                else tete.regler("calibration", JSONObject().put("valeur", v))
            }
            OutlinedTextField(
                value = cal, onValueChange = { cal = it }, singleLine = true,
                suffix = { Text("dBu", color = DOUX) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { envoyer() }),
                modifier = Modifier.weight(1f)
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = envoyer) { Text("OK") }
        }
    }
    if (confirmer) {
        AlertDialog(
            onDismissRequest = { confirmer = false },
            title = { Text("Changer le buffer") },
            text = { Text("Passer le buffer à $buffer × 2 ? L'audio coupe environ 5 secondes.") },
            confirmButton = {
                TextButton(onClick = {
                    confirmer = false
                    tete.regler("buffer", JSONObject().put("taille", buffer))
                }) { Text("Oui") }
            },
            dismissButton = { TextButton(onClick = { confirmer = false }) { Text("Annuler") } },
        )
    }
}

@Composable
private fun Etiquette(gauche: String, droite: String) {
    Row(Modifier.fillMaxWidth().padding(top = 10.dp)) {
        Text(gauche, color = DOUX, fontSize = 13.sp, modifier = Modifier.weight(1f))
        Text(droite, color = DOUX, fontSize = 13.sp)
    }
}

@Composable
private fun BlocCarte(b: Bloc, disponibles: List<String>, tete: Tete) {
    val id = JSONObject().put("id", b.id)
    fun avec(k: String, v: Any) = JSONObject(id.toString()).put(k, v)
    val bord = if (b.actif) ACCENT else Color(0xFF555555)
    Column(Modifier.padding(top = 10.dp).fillMaxWidth().alpha(if (b.actif) 1f else 0.55f)
        .clip(RoundedCornerShape(10.dp)).background(CARTE)
        .drawBehind { drawRect(bord, size = Size(4.dp.toPx(), size.height)) }) {
        run {
            Column(Modifier.padding(start = 16.dp, top = 12.dp, end = 12.dp, bottom = 12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(b.nom, color = TEXTE, fontSize = 16.sp, fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1f))
                    Button(
                        onClick = { tete.regler("actif", avec("actif", !b.actif)) },
                        colors = if (b.actif) ButtonDefaults.buttonColors(containerColor = OK, contentColor = Color.Black)
                        else ButtonDefaults.buttonColors(containerColor = Color(0xFF333333), contentColor = TEXTE)
                    ) { Text(if (b.actif) "Activé" else "Désactivé") }
                }
                val liste = if (b.chemin.isEmpty() || b.chemin in disponibles) disponibles else listOf(b.chemin) + disponibles
                var options = liste.map { it to nom(it) }
                if (b.id == 0) options = listOf("" to "(aucune pédale)") + options
                Choix(if (b.chemin.isEmpty()) "(aucune pédale)" else nom(b.chemin), options) {
                    tete.regler("modele", avec("chemin", it))
                }
                Etiquette("Output mode", "")
                val modes = listOf("calibrated" to "Calibrated", "normalized" to "Normalized")
                Choix(modes.firstOrNull { it.first == b.mode }?.second ?: b.mode, modes) {
                    tete.regler("mode", avec("mode", it))
                }
                Curseur("Qualité A2 (0 = léger, 1 = complet)", b.q, 0f, 1f, 0.05f, "") {
                    tete.regler("niveau", avec("sens", "q").put("valeur", it.toDouble()))
                }
                Curseur("Entrée", b.entree, -20f, 20f, 0.5f, " dB") {
                    tete.regler("niveau", avec("sens", "in").put("valeur", it.toDouble()))
                }
                Curseur("Sortie", b.sortie, -20f, 20f, 0.5f, " dB") {
                    tete.regler("niveau", avec("sens", "out").put("valeur", it.toDouble()))
                }
            }
        }
    }
}

@Composable
private fun Curseur(texte: String, valeur: Float, min: Float, max: Float, pas: Float, unite: String,
                    lacher: (Float) -> Unit) {
    var v by remember(valeur) { mutableFloatStateOf(valeur) }
    val crans = ((max - min) / pas).toInt() - 1
    Etiquette(texte, nombre(v) + unite)
    Slider(
        value = v,
        onValueChange = { v = Math.round(it / pas) * pas },
        onValueChangeFinished = { lacher(v) },
        valueRange = min..max,
        steps = crans,
        colors = SliderDefaults.colors(thumbColor = ACCENT, activeTrackColor = ACCENT),
    )
}
