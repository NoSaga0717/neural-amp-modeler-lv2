#!/usr/bin/env python3
"""Page web de la Tête NAM : http://tetenam.local:8080

Affiche en direct la charge DSP, les xruns, la température et le throttling.
Règle le buffer JACK et la calibration d'entrée, et la chaîne fixe
Pédale -> Ampli : activer ou désactiver chaque bloc, choisir le modèle,
l'output mode, la qualité A2 et les niveaux.
Uniquement la bibliothèque standard de Python : rien à installer.
Chaque changement est appliqué tout de suite et sauvegardé dans
/etc/tete-nam.conf : la tête redémarre comme on l'a laissée.
"""
import glob
import json
import re
import urllib.parse
import os
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import tetenam  # noqa: E402

PORT = int(os.environ.get("TETE_NAM_PORT", "8080"))
DOSSIER_MODELES = tetenam.DOSSIER_MODELES

verrou = threading.Lock()          # un seul échange avec mod-host à la fois
verrou_chaine = threading.RLock()  # une seule modification à la fois
etat = {
    "xruns": 0,
    "dsp": None,
    "histo": deque(maxlen=120),    # 2 minutes de charge DSP
    "throttled": "?",
    # Réglages en cours (même forme que tetenam.reglages()), sauvegardés
    # dans /etc/tete-nam.conf à chaque changement
    "r": None,
    "redemarrage": 0,              # heure du dernier redémarrage demandé
}


def reprendre_conf():
    """Au démarrage (ou quand le service redémarre), on repart des réglages :
    c'est ce que `tete-nam charger` vient de mettre en place."""
    with verrou_chaine:
        try:
            etat["r"] = tetenam.reglages()
        except OSError:
            etat["r"] = tetenam.reglages({})


def sauver():
    try:
        tetenam.ecrire_conf(etat["r"])
        return None
    except OSError as e:
        return f"Réglage appliqué mais pas sauvegardé ({e.strerror})"


def mod_host(commande):
    with verrou:
        try:
            m = tetenam.ModHost(attente=1)
        except SystemExit as e:              # tetenam sort en cas d'échec
            raise RuntimeError(str(e))
        try:
            return m.cmd(commande, ok_si_negatif=True)
        finally:
            m.s.close()


def ok(rep):
    return rep.startswith("resp ") and not rep.split()[1].startswith("-")


def trouver(i):
    for b in etat["r"]["blocs"]:
        if b["id"] == i:
            return b
    raise ValueError(f"Pas de bloc n°{i}")


def appliquer(cmds):
    """Envoie une suite de commandes à mod-host, s'arrête à la première erreur."""
    for cmd in cmds:
        rep = mod_host(cmd)
        if not ok(rep):
            return {"ok": False, "reponse": f"{cmd} : {rep}"}
    return {"ok": True}


def fini(r):
    """Sauvegarde si tout s'est bien passé, et le dit à la page."""
    if r.get("ok"):
        err = sauver()
        if err:
            return {"ok": False, "erreur": err}
    return r


# --- Tâches de fond -------------------------------------------------------

def suivre_journal():
    """Compte les xruns en lisant le journal du service, sans le relire en entier."""
    while True:
        depuis = tetenam.sh("systemctl show -p ActiveEnterTimestamp --value tete-nam") or "today"
        try:
            p = subprocess.Popen(["journalctl", "-u", "tete-nam", "-f", "-o", "cat", "-q",
                                  "--since", depuis], stdout=subprocess.PIPE, text=True,
                                 errors="replace")
        except OSError:
            time.sleep(10)
            continue
        etat["xruns"] = 0
        for ligne in p.stdout:
            if "Démarrage de JACK" in ligne:      # le service a redémarré
                etat["xruns"] = 0
            elif "Chaîne prête" in ligne:          # chaîne rechargée depuis la conf
                reprendre_conf()
            elif "xrun" in ligne.lower():
                etat["xruns"] += 1
        time.sleep(2)


def mesurer():
    n = 0
    while True:
        try:
            etat["dsp"] = float(mod_host("cpu_load").split()[2])
        except (RuntimeError, OSError, IndexError, ValueError):
            etat["dsp"] = None
        etat["histo"].append(etat["dsp"])
        if n % 10 == 0:
            etat["throttled"] = tetenam.sh("vcgencmd get_throttled").replace("throttled=", "")
        n += 1
        time.sleep(1)


def temperature():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000
    except OSError:
        return None


def disponibles():
    return sorted(glob.glob(os.path.join(DOSSIER_MODELES, "**", "*.nam"), recursive=True))


# --- API -------------------------------------------------------------------

def api_etat():
    r = etat["r"]
    return {
        "service": tetenam.sh("systemctl is-active tete-nam"),
        "dsp": etat["dsp"],
        "histo": list(etat["histo"]),
        "xruns": etat["xruns"],
        "temp": temperature(),
        "throttled": etat["throttled"],
        "reglages": {k: r[k] for k in ("RATE", "PERIOD", "NPERIODS", "CARD", "INPUT_DBU")},
        "buffers": tetenam.BUFFERS,
        "blocs": r["blocs"],
        "disponibles": disponibles(),
    }


def api_modele(d):
    with verrou_chaine:
        b = trouver(int(d["id"]))
        chemin = d["chemin"]
        if chemin == "" and b["id"] == 0:
            # Pédale sans modèle : on la laisse passer le son
            b["chemin"], b["actif"] = "", False
            return fini(appliquer([f"bypass {b['id']} 1"]))
        if chemin not in disponibles():
            return {"ok": False, "erreur": "Fichier hors de ~/nam"}
        cmds = [f"patch_set {b['id']} {tetenam.q(tetenam.MODEL_PROP)} {tetenam.q(chemin)}"]
        if b["actif"]:
            cmds.append(f"bypass {b['id']} 0")
        r = appliquer(cmds)
        if r["ok"]:
            b["chemin"] = chemin
        return fini(r)


def api_niveau(d):
    with verrou_chaine:
        b = trouver(int(d["id"]))
        sens, val = d["sens"], float(d["valeur"])
        if sens == "q":
            val, port = max(0.0, min(1.0, val)), "quality_scale"
        elif sens in ("in", "out"):
            val = max(-20.0, min(20.0, val))
            port = "input_level" if sens == "in" else "output_level"
        else:
            return {"ok": False, "erreur": "Réglage inconnu"}
        r = appliquer([f"param_set {b['id']} {port} {val}"])
        if r["ok"]:
            b[sens] = val
        return fini(r)


def api_mode(d):
    with verrou_chaine:
        b = trouver(int(d["id"]))
        mode = d["mode"]
        if mode not in tetenam.MODES:
            return {"ok": False, "erreur": "Output mode inconnu"}
        r = appliquer([f"param_set {b['id']} output_mode {tetenam.MODES[mode]}"])
        if r["ok"]:
            b["mode"] = mode
        return fini(r)


def api_actif(d):
    with verrou_chaine:
        b = trouver(int(d["id"]))
        actif = bool(d["actif"])
        if actif and not b["chemin"]:
            return {"ok": False, "erreur": f"Choisissez d'abord un modèle pour : {b['nom']}"}
        # bypass 1 = le son passe sans traitement
        r = appliquer([f"bypass {b['id']} {0 if actif else 1}"])
        if r["ok"]:
            b["actif"] = actif
        return fini(r)


def api_calibration(d):
    with verrou_chaine:
        val = float(d["valeur"])
        if not -60 <= val <= 60:
            return {"ok": False, "erreur": "Calibration entre -60 et +60 dBu"}
        # Même valeur pour les deux NAM : c'est l'entrée de la carte son
        r = appliquer([f"param_set {b['id']} input_calibration {val}"
                       for b in etat["r"]["blocs"]])
        if r["ok"]:
            etat["r"]["INPUT_DBU"] = val
        return fini(r)


def api_buffer(d):
    with verrou_chaine:
        taille = int(d["taille"])
        if taille not in tetenam.BUFFERS:
            return {"ok": False, "erreur": "Taille de buffer non proposée"}
        if time.time() - etat["redemarrage"] < 10:
            return {"ok": False, "erreur": "Redémarrage déjà en cours, patientez"}
        etat["r"]["PERIOD"], etat["r"]["NPERIODS"] = taille, tetenam.NPERIODS
        err = sauver()
        if err:
            return {"ok": False, "erreur": err}
        # JACK ne change pas de buffer à chaud : on relance le service audio.
        # Autorisé sans mot de passe par /etc/sudoers.d/tete-nam (install.sh).
        p = subprocess.run(["sudo", "-n", "systemctl", "restart", "--no-block", "tete-nam"],
                           capture_output=True, text=True, timeout=10)
        if p.returncode:
            return {"ok": False, "erreur": "Buffer sauvegardé, mais redémarrage refusé : "
                    "relancez sudo ./tete-nam/install.sh, ou sudo systemctl restart tete-nam"}
        etat["redemarrage"] = time.time()
        return {"ok": True}


TAILLE_MAX = 50 * 1024 * 1024   # 50 Mo, largement plus qu'un .nam


def api_envoyer(nom, contenu):
    """Reçoit un fichier .nam envoyé depuis la page et le range dans ~/nam."""
    nom = os.path.basename(nom).strip().replace(" ", "_")
    nom = re.sub(r"[^\w.\-]", "_", nom)              # pas de caractères bizarres
    if not nom.lower().endswith(".nam") or nom.startswith("."):
        return {"ok": False, "erreur": f"{nom} : seuls les fichiers .nam sont acceptés"}
    try:
        donnees = json.loads(contenu)
        assert isinstance(donnees, dict) and "architecture" in donnees
    except Exception:
        return {"ok": False, "erreur": f"{nom} : ce n'est pas un modèle NAM valide"}
    os.makedirs(DOSSIER_MODELES, exist_ok=True)
    final = os.path.join(DOSSIER_MODELES, nom)
    temp = final + ".envoi"
    with open(temp, "wb") as f:                       # écrit à côté, puis renomme :
        f.write(contenu)                              # jamais de fichier à moitié écrit
    existait = os.path.exists(final)
    os.replace(temp, final)
    return {"ok": True, "nom": nom, "remplace": existait}


ROUTES = {"/api/modele": api_modele, "/api/niveau": api_niveau, "/api/actif": api_actif,
          "/api/mode": api_mode, "/api/calibration": api_calibration, "/api/buffer": api_buffer}


class Gestionnaire(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass                                   # pas de bruit dans le journal

    def envoyer(self, code, corps, type_):
        b = corps.encode() if isinstance(corps, str) else corps
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/":
            self.envoyer(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/etat":
            self.envoyer(200, json.dumps(api_etat()), "application/json")
        else:
            self.envoyer(404, "introuvable", "text/plain")

    def do_POST(self):
        if self.path == "/api/envoyer":
            n = int(self.headers.get("Content-Length", 0))
            if n > TAILLE_MAX:
                r = {"ok": False, "erreur": "Fichier trop gros (50 Mo maximum)"}
            else:
                nom = urllib.parse.unquote(self.headers.get("X-Nom-Fichier", ""))
                try:
                    r = api_envoyer(nom, self.rfile.read(n))
                except Exception as e:
                    r = {"ok": False, "erreur": str(e)}
            return self.envoyer(200, json.dumps(r), "application/json")
        if self.path not in ROUTES:
            return self.envoyer(404, "introuvable", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        try:
            r = ROUTES[self.path](json.loads(self.rfile.read(n) or b"{}"))
        except Exception as e:                  # on renvoie l'erreur à la page
            r = {"ok": False, "erreur": str(e)}
        self.envoyer(200, json.dumps(r), "application/json")


PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tête NAM</title>
<style>
:root{--bg:#141414;--carte:#1f1f1f;--texte:#eee;--doux:#999;--ok:#4caf50;--moyen:#e0a800;--mal:#e5484d;--accent:#d9822b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--texte);font:16px/1.4 system-ui,sans-serif;padding:16px;max-width:720px;margin:auto}
h1{font-size:22px;margin:0 0 12px;display:flex;justify-content:space-between;align-items:center}
h2{font-size:15px;color:var(--doux);font-weight:500;margin:20px 0 0}
#service{font-size:13px;padding:3px 10px;border-radius:12px;background:#333}
.grille{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.carte{background:var(--carte);border-radius:10px;padding:12px}
.titre{color:var(--doux);font-size:13px}
.valeur{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums}
canvas{width:100%;height:70px;display:block;margin-top:6px}
section.carte{margin-top:10px;border-left:4px solid var(--accent);transition:opacity .2s}
section.off{opacity:.45;border-left-color:#555}
.entete{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.entete b{flex:1;font-size:16px}
button{font:inherit;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;color:var(--texte);background:#333}
button.on{background:var(--ok);color:#000;font-weight:600}
button.retirer{background:none;color:var(--doux);font-size:20px;padding:4px 10px}
#envoyer{width:100%;margin-top:10px;padding:12px;font-size:17px;background:#2a2a2a;border:1px dashed #555}
#infoEnvoi{font-size:13px;color:var(--doux);margin-top:6px;white-space:pre-line}
.ligne{display:flex;gap:8px;align-items:center;margin-top:6px}
.ligne select{flex:1}
input[type=number]{flex:1;min-width:0;background:#2a2a2a;color:var(--texte);border:1px solid #444;border-radius:6px;padding:8px;font-size:15px}
.unite{color:var(--doux)}
button:disabled{opacity:.4;cursor:default}
select,input[type=range]{width:100%;accent-color:var(--accent)}
select{background:#2a2a2a;color:var(--texte);border:1px solid #444;border-radius:6px;padding:8px;font-size:15px}
label{display:flex;justify-content:space-between;color:var(--doux);font-size:13px;margin-top:10px}
.pied{color:var(--doux);font-size:12px;margin-top:16px}
#msg{color:var(--mal);font-size:13px;min-height:1em;margin-top:8px}
</style></head><body>
<h1>Tête NAM <span id="service">…</span></h1>
<div class="grille">
 <div class="carte" style="grid-column:1/-1"><div class="titre">Charge DSP</div>
  <div class="valeur" id="dsp">–</div><canvas id="graphe"></canvas></div>
 <div class="carte"><div class="titre">Xruns (craquements)</div><div class="valeur" id="xruns">–</div></div>
 <div class="carte"><div class="titre">Température</div><div class="valeur" id="temp">–</div></div>
 <div class="carte"><div class="titre">Throttling</div><div class="valeur" id="thr" style="font-size:20px">–</div></div>
 <div class="carte"><div class="titre">Audio</div><div id="audio" style="margin-top:6px">–</div></div>
</div>
<h2>Réglages audio</h2>
<div class="carte" style="margin-top:10px">
 <label>Buffer JACK (2 périodes) <span id="latence"></span></label>
 <div class="ligne"><select id="buffer"></select><button id="appliquerBuffer">Appliquer</button></div>
 <label>Calibration d'entrée (dBu pour 0 dBFS, M4 : 16) <span id="calActuelle"></span></label>
 <div class="ligne"><input type="number" id="calibration" min="-60" max="60" step="0.1" inputmode="decimal"><span class="unite">dBu</span><button id="appliquerCal">OK</button></div>
</div>
<h2>Chaîne (entrée → Pédale → Ampli → power amp)</h2>
<div id="chaine"></div>
<h2>Fichiers</h2>
<button id="envoyer">Envoyer des fichiers .nam vers la tête</button>
<input type="file" id="fichiers" accept=".nam" multiple hidden>
<div id="infoEnvoi"></div>
<div id="msg"></div>
<div class="pied">Chaque réglage est appliqué tout de suite et sauvegardé dans /etc/tete-nam.conf : la tête redémarre comme vous l'avez laissée. Changer le buffer relance l'audio (environ 5 s de silence).</div>
<script>
const $=id=>document.getElementById(id);
let construit="", occupe=false;
const couleur=(v,a,b)=>v==null?"":v<a?"var(--ok)":v<b?"var(--moyen)":"var(--mal)";
const nom=p=>p.split("/").pop();
async function post(url,d){
  try{
    const r=await (await fetch(url,{method:"POST",body:JSON.stringify(d||{})})).json();
    $("msg").textContent=r.ok?"":(r.erreur||r.reponse||"Erreur");
  }catch(e){$("msg").textContent="Pas de réponse de la tête";}
  construit="";maj();
}
function curseur(s,sens,txt,min,max,pas,unite){
  return `<label>${txt} <span id="v${sens}${s.id}">${s[sens]}${unite}</span></label>
   <input type="range" min="${min}" max="${max}" step="${pas}" value="${s[sens]}" data-id="${s.id}" data-sens="${sens}" data-unite="${unite}">`;
}
function chaine(e){
  const cle=JSON.stringify([e.blocs,e.disponibles]);
  if(cle===construit||occupe)return; construit=cle;
  let h="";
  e.blocs.forEach(s=>{
    const liste=(s.chemin===""||e.disponibles.includes(s.chemin))?e.disponibles:[s.chemin,...e.disponibles];
    let opts=liste.map(f=>`<option value="${f}"${f===s.chemin?" selected":""}>${nom(f)}</option>`).join("");
    if(s.id===0)opts=`<option value=""${s.chemin===""?" selected":""}>(aucune pédale)</option>`+opts;
    const modes=[["calibrated","Calibrated"],["normalized","Normalized"]]
      .map(([v,t])=>`<option value="${v}"${v===s.mode?" selected":""}>${t}</option>`).join("");
    h+=`<section class="carte${s.actif?"":" off"}">
     <div class="entete"><b>${s.nom}</b>
      <button class="${s.actif?"on":""}" data-actif="${s.id}" data-etat="${s.actif?1:0}">${s.actif?"Activé":"Désactivé"}</button></div>
     <select data-id="${s.id}" class="mod">${opts}</select>
     <label>Output mode</label>
     <select data-id="${s.id}" class="mode">${modes}</select>
     ${curseur(s,"q","Qualité A2 (0 = léger, 1 = complet)",0,1,0.05,"")}
     ${curseur(s,"in","Entrée",-20,20,0.5," dB")}
     ${curseur(s,"out","Sortie",-20,20,0.5," dB")}</section>`;
  });
  $("chaine").innerHTML=h;
  document.querySelectorAll(".mod").forEach(x=>x.onchange=()=>post("/api/modele",{id:x.dataset.id,chemin:x.value}));
  document.querySelectorAll(".mode").forEach(x=>x.onchange=()=>post("/api/mode",{id:x.dataset.id,mode:x.value}));
  document.querySelectorAll("[data-actif]").forEach(b=>b.onclick=()=>post("/api/actif",{id:b.dataset.actif,actif:b.dataset.etat!=="1"}));
  document.querySelectorAll("#chaine input[type=range]").forEach(r=>{
    r.oninput=()=>{$("v"+r.dataset.sens+r.dataset.id).textContent=r.value+r.dataset.unite;occupe=true;};
    r.onchange=async()=>{occupe=false;await post("/api/niveau",{id:r.dataset.id,sens:r.dataset.sens,valeur:r.value});};
  });
}
let audioConstruit="";
function audio(e){
  const r=e.reglages, cle=JSON.stringify([r,e.buffers]);
  $("latence").textContent=`actuel : ${r.PERIOD} × ${r.NPERIODS} ≈ ${(r.PERIOD*r.NPERIODS/r.RATE*1000).toFixed(1)} ms`;
  $("calActuelle").textContent=`actuel : ${r.INPUT_DBU} dBu`;
  if(cle===audioConstruit)return; audioConstruit=cle;
  $("buffer").innerHTML=e.buffers.map(t=>`<option value="${t}"${t===r.PERIOD?" selected":""}>${t} (≈ ${(t*2/r.RATE*1000).toFixed(1)} ms)</option>`).join("");
  if(document.activeElement!==$("calibration"))$("calibration").value=r.INPUT_DBU;
}
$("appliquerBuffer").onclick=async()=>{
  const t=+$("buffer").value;
  if(!confirm(`Passer le buffer à ${t} × 2 ? L'audio coupe environ 5 secondes.`))return;
  $("appliquerBuffer").disabled=true;
  await post("/api/buffer",{taille:t});
  setTimeout(()=>$("appliquerBuffer").disabled=false,10000);
};
const envoyerCal=()=>post("/api/calibration",{valeur:$("calibration").value}).then(()=>{audioConstruit="";});
$("appliquerCal").onclick=envoyerCal;
$("calibration").onkeydown=ev=>{if(ev.key==="Enter")envoyerCal();};
$("envoyer").onclick=()=>$("fichiers").click();
$("fichiers").onchange=async()=>{
  const liste=[...$("fichiers").files], lignes=[];
  for(const [n,f] of liste.entries()){
    $("infoEnvoi").textContent=[...lignes,`Envoi ${n+1}/${liste.length} : ${f.name}…`].join("\n");
    try{
      const r=await (await fetch("/api/envoyer",{method:"POST",body:f,
        headers:{"X-Nom-Fichier":encodeURIComponent(f.name)}})).json();
      lignes.push(r.ok?`✓ ${r.nom}${r.remplace?" (remplacé)":""}`:`✗ ${r.erreur}`);
    }catch(e){lignes.push(`✗ ${f.name} : pas de réponse de la tête`);}
  }
  $("infoEnvoi").textContent=lignes.join("\n");
  $("fichiers").value="";construit="";maj();
};
function graphe(h){
  const c=$("graphe"),x=c.getContext("2d"),w=c.width=c.clientWidth*devicePixelRatio,ht=c.height=70*devicePixelRatio;
  x.clearRect(0,0,w,ht);
  x.strokeStyle="#333";x.beginPath();[70,85].forEach(s=>{const y=ht-s/100*ht;x.moveTo(0,y);x.lineTo(w,y)});x.stroke();
  x.strokeStyle=getComputedStyle(document.body).getPropertyValue("--accent");x.lineWidth=2*devicePixelRatio;x.beginPath();
  h.forEach((v,i)=>{if(v==null)return;const px=i/119*w,py=ht-Math.min(v,100)/100*ht;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke();
}
async function maj(){
  try{
    const e=await (await fetch("/api/etat")).json();
    $("service").textContent=e.service;
    $("service").style.background=e.service==="active"?"var(--ok)":"var(--mal)";
    $("dsp").textContent=e.dsp==null?"–":e.dsp.toFixed(1)+" %";$("dsp").style.color=couleur(e.dsp,70,85);
    $("xruns").textContent=e.xruns;$("xruns").style.color=e.xruns?"var(--mal)":"var(--ok)";
    $("temp").textContent=e.temp==null?"–":e.temp.toFixed(0)+" °C";$("temp").style.color=couleur(e.temp,70,80);
    $("thr").textContent=e.throttled==="0x0"?"aucun":e.throttled;$("thr").style.color=e.throttled==="0x0"?"var(--ok)":"var(--mal)";
    const r=e.reglages;$("audio").textContent=`${r.RATE/1000} kHz, buffer ${r.PERIOD} × ${r.NPERIODS}, entrée ${r.INPUT_DBU} dBu`;
    graphe(e.histo);chaine(e);audio(e);
  }catch(err){$("service").textContent="hors ligne";$("service").style.background="var(--mal)";}
}
maj();setInterval(maj,1000);
</script></body></html>"""


def main():
    reprendre_conf()
    threading.Thread(target=suivre_journal, daemon=True).start()
    threading.Thread(target=mesurer, daemon=True).start()
    print(f"Page web : http://{os.uname().nodename}.local:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Gestionnaire).serve_forever()


if __name__ == "__main__":
    main()
