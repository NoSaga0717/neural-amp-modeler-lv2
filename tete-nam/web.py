#!/usr/bin/env python3
"""Page web de la Tête NAM : http://tetenam.local:8080

Affiche en direct la charge DSP, les xruns, la température et le throttling,
et permet de changer de modèle et de régler les niveaux sans terminal.
Uniquement la bibliothèque standard de Python : rien à installer.
Les changements faits ici sont immédiats mais pas sauvegardés : au
redémarrage, on repart de /etc/tete-nam.conf.
"""
import glob
import json
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
DOSSIER_MODELES = os.path.expanduser("~/nam")

verrou = threading.Lock()          # un seul échange avec mod-host à la fois
etat = {
    "xruns": 0,
    "dsp": None,
    "histo": deque(maxlen=120),    # 2 minutes de charge DSP
    "throttled": "?",
    "modeles": {},                 # numéro (0, 1) -> chemin
    "niveaux": {},                 # numéro -> {"in": dB, "out": dB}
}


def conf():
    try:
        return tetenam.lire_conf()
    except OSError:
        return {}


def reprendre_conf():
    """Au démarrage (ou quand le service redémarre), on repart des réglages."""
    c = conf()
    etat["modeles"] = {i: m for i, m in enumerate((c.get("MODEL1", ""), c.get("MODEL2", ""))) if m}
    etat["niveaux"] = {i: {"in": float(c.get("IN_DB", 0)), "out": float(c.get("OUT_DB", 0)),
                           "q": float(c.get("QUALITY", 0))}
                       for i in etat["modeles"]}


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


# --- API -------------------------------------------------------------------

def api_etat():
    c = conf()
    return {
        "service": tetenam.sh("systemctl is-active tete-nam"),
        "dsp": etat["dsp"],
        "histo": list(etat["histo"]),
        "xruns": etat["xruns"],
        "temp": temperature(),
        "throttled": etat["throttled"],
        "reglages": {k: c.get(k) for k in ("RATE", "PERIOD", "NPERIODS", "CARD")},
        "modeles": {str(i): m for i, m in etat["modeles"].items()},
        "niveaux": {str(i): v for i, v in etat["niveaux"].items()},
        "disponibles": sorted(glob.glob(os.path.join(DOSSIER_MODELES, "**", "*.nam"),
                                        recursive=True)),
    }


def api_modele(d):
    i, chemin = int(d["num"]), d["chemin"]
    if i not in etat["modeles"]:
        return {"ok": False, "erreur": f"Pas de modèle {i + 1} dans la chaîne"}
    if chemin not in api_etat()["disponibles"]:
        return {"ok": False, "erreur": "Fichier hors de ~/nam"}
    rep = mod_host(f"patch_set {i} {tetenam.q(tetenam.MODEL_PROP)} {tetenam.q(chemin)}")
    ok = rep.startswith("resp 0")
    if ok:
        etat["modeles"][i] = chemin
    return {"ok": ok, "reponse": rep}


def api_niveau(d):
    i, sens, db = int(d["num"]), d["sens"], float(d["db"])
    if i not in etat["modeles"] or sens not in ("in", "out", "q"):
        return {"ok": False}
    if sens == "q":
        db = max(0.0, min(1.0, db))
    else:
        db = max(-20.0, min(20.0, db))
    port = {"in": "input_level", "out": "output_level", "q": "quality_scale"}[sens]
    rep = mod_host(f"param_set {i} {port} {db}")
    ok = rep.startswith("resp 0")
    if ok:
        etat["niveaux"][i][sens] = db
    return {"ok": ok, "reponse": rep}


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
        n = int(self.headers.get("Content-Length", 0))
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/modele":
                r = api_modele(d)
            elif self.path == "/api/niveau":
                r = api_niveau(d)
            else:
                return self.envoyer(404, "introuvable", "text/plain")
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
#service{font-size:13px;padding:3px 10px;border-radius:12px;background:#333}
.grille{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.carte{background:var(--carte);border-radius:10px;padding:12px}
.titre{color:var(--doux);font-size:13px}
.valeur{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums}
canvas{width:100%;height:70px;display:block;margin-top:6px}
section{margin-top:14px}
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
<div id="chaine"></div>
<div id="msg"></div>
<div class="pied">Les changements sont immédiats mais pas sauvegardés : au redémarrage, la tête repart de /etc/tete-nam.conf.</div>
<script>
const $=id=>document.getElementById(id);
let construit="", occupe=false;
const couleur=(v,a,b)=>v==null?"":v<a?"var(--ok)":v<b?"var(--moyen)":"var(--mal)";
const nom=p=>p.split("/").pop();
async function post(url,d){
  const r=await (await fetch(url,{method:"POST",body:JSON.stringify(d)})).json();
  $("msg").textContent=r.ok?"":(r.erreur||r.reponse||"Erreur");
}
function chaine(e){
  const cle=JSON.stringify([e.modeles,e.disponibles]);
  if(cle===construit||occupe)return; construit=cle;
  let h="";
  for(const [i,m] of Object.entries(e.modeles)){
    const n=e.niveaux[i]||{in:0,out:0,q:0};
    const opts=(e.disponibles.includes(m)?e.disponibles:[m,...e.disponibles])
      .map(f=>`<option value="${f}"${f===m?" selected":""}>${nom(f)}</option>`).join("");
    h+=`<section class="carte"><div class="titre">Modèle ${+i+1}</div>
     <select data-num="${i}" class="mod">${opts}</select>
     <label>Qualité A2 (0 = léger, 1 = complet) <span id="vq${i}">${n.q}</span></label>
     <input type="range" min="0" max="1" step="0.05" value="${n.q}" data-num="${i}" data-sens="q" data-unite="">
     <label>Entrée <span id="vi${i}">${n.in} dB</span></label>
     <input type="range" min="-20" max="20" step="0.5" value="${n.in}" data-num="${i}" data-sens="in" data-unite=" dB">
     <label>Sortie <span id="vo${i}">${n.out} dB</span></label>
     <input type="range" min="-20" max="20" step="0.5" value="${n.out}" data-num="${i}" data-sens="out" data-unite=" dB"></section>`;
  }
  $("chaine").innerHTML=h;
  document.querySelectorAll(".mod").forEach(s=>s.onchange=()=>post("/api/modele",{num:s.dataset.num,chemin:s.value}));
  document.querySelectorAll("input[type=range]").forEach(r=>{
    r.oninput=()=>{$({in:"vi",out:"vo",q:"vq"}[r.dataset.sens]+r.dataset.num).textContent=r.value+r.dataset.unite;occupe=true;};
    r.onchange=async()=>{await post("/api/niveau",{num:r.dataset.num,sens:r.dataset.sens,db:r.value});occupe=false;construit="";};
  });
}
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
    const r=e.reglages;$("audio").textContent=`${r.RATE/1000} kHz, buffer ${r.PERIOD} × ${r.NPERIODS}`;
    graphe(e.histo);chaine(e);
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
