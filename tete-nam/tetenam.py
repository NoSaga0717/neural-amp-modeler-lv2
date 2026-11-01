#!/usr/bin/env python3
"""Petit outil de pilotage de la Tête NAM (parle à mod-host sur le port 5555).

  tete-nam charger              charge la chaîne décrite dans /etc/tete-nam.conf
  tete-nam modele pedale FICH   change le modèle de la pédale (ou ampli) à chaud
  tete-nam cpu                  affiche la charge DSP de JACK
  tete-nam etat                 résumé : service, DSP, xruns, température
  tete-nam migrer               réécrit /etc/tete-nam.conf au format actuel

La chaîne est fixe : entrée -> Pédale -> Ampli -> sorties.
"""
import glob
import os
import shlex
import socket
import subprocess
import sys
import time

CONF = os.environ.get("TETE_NAM_CONF", "/etc/tete-nam.conf")
HOST, PORT = "127.0.0.1", 5555
PLUGIN = "http://github.com/mikeoliphant/neural-amp-modeler-lv2"
MODEL_PROP = PLUGIN + "#model"
DOSSIER_MODELES = os.path.expanduser("~/nam")

# Les deux blocs de la chaîne, dans l'ordre. "id" = numéro d'instance mod-host.
BLOCS = [
    {"id": 0, "cle": "PEDALE", "nom": "Pédale", "mode": "calibrated"},
    {"id": 1, "cle": "AMPLI", "nom": "Ampli", "mode": "normalized"},
]
# Valeurs du port "output_mode" du plugin (Raw = 0 n'est pas proposé)
MODES = {"normalized": 1, "calibrated": 2}
BUFFERS = (64, 128, 256, 512)
NPERIODS = 2
INPUT_DBU_DEFAUT = 16.0


def lire_conf():
    conf = {}
    with open(CONF) as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, val = ligne.split("=", 1)
            vals = shlex.split(val)
            conf[cle.strip()] = " ".join(vals)
    return conf


def nombre(texte, defaut, mini=None, maxi=None):
    try:
        v = float(texte)
    except (TypeError, ValueError):
        return defaut
    if mini is not None:
        v = max(mini, v)
    if maxi is not None:
        v = min(maxi, v)
    return v


def premier_modele():
    tous = sorted(glob.glob(os.path.join(DOSSIER_MODELES, "**", "*.nam"), recursive=True))
    return tous[0] if tous else ""


def reglages(c=None):
    """Lit la conf et la met au propre. Comprend aussi l'ancien format
    (MODEL1, MODEL2, IN_DB, OUT_DB, QUALITY) : MODEL1 seul = l'ampli,
    MODEL1 + MODEL2 = la pédale puis l'ampli."""
    if c is None:
        c = lire_conf()
    ancien = "AMPLI_MODEL" not in c and "PEDALE_MODEL" not in c
    if ancien:
        m1, m2 = c.get("MODEL1", ""), c.get("MODEL2", "")
        modeles = {"PEDALE": m1 if m2 else "", "AMPLI": m2 or m1}
    periode = int(nombre(c.get("PERIOD"), 256))
    r = {
        "CARD": c.get("CARD", "M4"),
        "RATE": int(nombre(c.get("RATE"), 48000)),
        "PERIOD": periode if periode in BUFFERS else 256,
        "NPERIODS": NPERIODS if ancien else int(nombre(c.get("NPERIODS"), NPERIODS, 2, 3)),
        "INPUT": c.get("INPUT", "system:capture_1"),
        "OUTPUTS": c.get("OUTPUTS", "system:playback_1 system:playback_2"),
        "INPUT_DBU": nombre(c.get("INPUT_DBU"), INPUT_DBU_DEFAUT, -60, 60),
        "blocs": [],
    }
    for b in BLOCS:
        k = b["cle"]
        if ancien:
            chemin, actif = modeles[k], bool(modeles[k])
            q = nombre(c.get("QUALITY"), 0.0, 0, 1)
            e = nombre(c.get("IN_DB"), 0.0, -20, 20)
            s = nombre(c.get("OUT_DB"), 0.0, -20, 20)
            mode = b["mode"]
        else:
            chemin = c.get(k + "_MODEL", "")
            actif = c.get(k + "_ACTIF", "1") != "0"
            q = nombre(c.get(k + "_QUALITY"), 0.0, 0, 1)
            e = nombre(c.get(k + "_IN_DB"), 0.0, -20, 20)
            s = nombre(c.get(k + "_OUT_DB"), 0.0, -20, 20)
            mode = c.get(k + "_MODE", b["mode"]).lower()
            if mode not in MODES:
                mode = b["mode"]
        r["blocs"].append({"id": b["id"], "cle": k, "nom": b["nom"], "chemin": chemin,
                           "actif": actif, "mode": mode, "q": q, "in": e, "out": s})
    # L'ampli doit toujours avoir un modèle : sinon le premier .nam de ~/nam
    ampli = r["blocs"][1]
    if not os.path.isfile(ampli["chemin"]):
        ampli["chemin"] = premier_modele()
    pedale = r["blocs"][0]
    if pedale["chemin"] and not os.path.isfile(pedale["chemin"]):
        pedale["chemin"] = ""
    if not pedale["chemin"]:
        pedale["actif"] = False
    return r


MODELE_CONF = """\
# Réglages de la Tête NAM (lu au démarrage par le service tete-nam)
# La page web http://tetenam.local:8080 réécrit ce fichier à chaque
# changement. À la main : sudo nano /etc/tete-nam.conf
# puis sudo systemctl restart tete-nam

# Carte son (nom ALSA, visible avec : cat /proc/asound/cards)
CARD={CARD}

# Fréquence d'échantillonnage : doit être celle des modèles (48 kHz en général)
RATE={RATE}

# Taille du buffer JACK : 64, 128, 256 ou 512 (réglable depuis la page)
PERIOD={PERIOD}

# Nombre de périodes JACK (2 = le moins de latence)
NPERIODS={NPERIODS}

# Entrée guitare de la M4 (capture_1 = entrée 1 en façade)
INPUT={INPUT}

# Sorties de la M4 vers l'ampli (playback_1 et 2 = sorties principales,
# réglées par le gros bouton MONITOR)
OUTPUTS="{OUTPUTS}"

# Calibration d'entrée : niveau en dBu qui donne 0 dBFS sur l'entrée de la
# carte son. Appliquée aux deux NAM (la pédale et l'ampli).
INPUT_DBU={INPUT_DBU}

# Chaîne fixe : entrée -> PEDALE -> AMPLI -> sorties
#   _MODEL   fichier .nam (pédale : vide = aucune). Éviter les espaces.
#   _ACTIF   1 = activé, 0 = le son passe sans traitement
#   _MODE    calibrated ou normalized (output mode du plugin NAM)
#   _QUALITY qualité NAM A2, de 0.0 (le plus léger) à 1.0 (complet)
#   _IN_DB, _OUT_DB  niveaux en dB (-20 à +20) avant et après le modèle
"""


def ecrire_conf(r):
    texte = MODELE_CONF.format(**r)
    for b in r["blocs"]:
        k = b["cle"]
        texte += (f"\n{k}_MODEL={shlex.quote(b['chemin']) if b['chemin'] else ''}\n"
                  f"{k}_ACTIF={1 if b['actif'] else 0}\n"
                  f"{k}_MODE={b['mode']}\n"
                  f"{k}_QUALITY={b['q']:g}\n"
                  f"{k}_IN_DB={b['in']:g}\n"
                  f"{k}_OUT_DB={b['out']:g}\n")
    # Réécriture sur place (le dossier /etc n'est pas à nous), puis sync
    with open(CONF, "w") as f:
        f.write(texte)
        f.flush()
        os.fsync(f.fileno())


class ModHost:
    def __init__(self, attente=30):
        fin = time.time() + attente
        while True:
            try:
                self.s = socket.create_connection((HOST, PORT), timeout=10)
                return
            except OSError:
                if time.time() > fin:
                    sys.exit("mod-host ne répond pas sur le port 5555 "
                             "(le service tete-nam tourne-t-il ?)")
                time.sleep(0.5)

    def cmd(self, texte, ok_si_negatif=False):
        self.s.sendall(texte.encode() + b"\0")
        rep = b""
        while not rep.endswith(b"\0"):
            morceau = self.s.recv(1024)
            if not morceau:
                break
            rep += morceau
        rep = rep.rstrip(b"\0").decode(errors="replace")
        parts = rep.split()
        if len(parts) >= 2 and parts[0] == "resp" and parts[1].lstrip("-").isdigit():
            if int(parts[1]) < 0 and not ok_si_negatif:
                sys.exit(f"Erreur mod-host pour « {texte} » : {rep}")
        return rep


def q(x):
    return '"' + x.replace('"', '\\"') + '"'


def commandes_bloc(b, input_dbu):
    """Commandes mod-host qui mettent une instance NAM dans l'état du bloc."""
    i = b["id"]
    cmds = [f"param_set {i} input_level {b['in']}",
            f"param_set {i} output_level {b['out']}",
            f"param_set {i} quality_scale {b['q']}",
            f"param_set {i} input_calibration {input_dbu}",
            f"param_set {i} output_mode {MODES[b['mode']]}"]
    if b["chemin"]:
        cmds.append(f"patch_set {i} {q(MODEL_PROP)} {q(b['chemin'])}")
    # bypass 1 = le son passe sans traitement (aussi quand il n'y a pas de modèle)
    cmds.append(f"bypass {i} {0 if b['actif'] and b['chemin'] else 1}")
    return cmds


def liens(r):
    """Entrée -> Pédale -> Ampli -> sorties."""
    a, b = (f"effect_{x['id']}" for x in r["blocs"])
    l = [(r["INPUT"], f"{a}:input"), (f"{a}:output", f"{b}:input")]
    l += [(f"{b}:output", s) for s in r["OUTPUTS"].split()]
    return l


def charger():
    r = reglages()
    if not r["blocs"][1]["chemin"]:
        sys.exit("Aucun modèle pour l'ampli : copiez un fichier .nam dans ~/nam")
    mh = ModHost()
    for b in r["blocs"]:
        mh.cmd(f"add {q(PLUGIN)} {b['id']}")
        for cmd in commandes_bloc(b, r["INPUT_DBU"]):
            mh.cmd(cmd)
        print(f"{b['nom']} : {b['chemin'] or 'aucun modèle'} ({b['mode']}"
              f"{'' if b['actif'] else ', désactivée'})")
    for a, b in liens(r):
        mh.cmd(f"connect {q(a)} {q(b)}")
    print(f"Calibration d'entrée : {r['INPUT_DBU']:g} dBu")
    print("Chaîne prête.")


def changer_modele(qui, chemin):
    noms = {"pedale": 0, "pédale": 0, "1": 0, "ampli": 1, "2": 1}
    if qui.lower() not in noms:
        sys.exit("Indiquez pedale ou ampli")
    open(chemin, "rb").close()
    i = noms[qui.lower()]
    rep = ModHost(attente=2).cmd(f"patch_set {i} {q(MODEL_PROP)} {q(os.path.abspath(chemin))}")
    print(rep)


def cpu():
    rep = ModHost(attente=2).cmd("cpu_load")
    return float(rep.split()[2])


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return "?"


def etat():
    print("Service      :", sh("systemctl is-active tete-nam"))
    try:
        print(f"Charge DSP   : {cpu():.1f} %")
    except SystemExit as e:
        print("Charge DSP   : indisponible -", e)
    depuis = sh("systemctl show -p ActiveEnterTimestamp --value tete-nam")
    xruns = sh(f"journalctl -u tete-nam --since '{depuis}' --no-pager -q "
               "| grep -ci xrun") if depuis else "?"
    print("Xruns        :", xruns or "0", "(depuis le dernier démarrage du service)")
    print("Température  :", sh("vcgencmd measure_temp").replace("temp=", ""))
    thr = sh("vcgencmd get_throttled").replace("throttled=", "")
    print("Throttling   :", thr, "(0x0 = parfait)" if thr == "0x0"
          else "(PAS 0x0 : alim trop faible ou trop chaud)")
    print("Gouverneur   :", sh("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"))
    r = reglages()
    print(f"Réglages     : {r['RATE']} Hz, buffer {r['PERIOD']} x {r['NPERIODS']}, "
          f"entrée {r['INPUT_DBU']:g} dBu")
    for b in r["blocs"]:
        print(f"{b['nom']:<13}: {b['chemin'] or 'aucun modèle'} ({b['mode']}, "
              f"{'activée' if b['actif'] else 'désactivée'})")


def main():
    a = sys.argv[1:]
    if a[:1] == ["charger"]:
        charger()
    elif a[:1] == ["modele"] and len(a) == 3:
        changer_modele(a[1], a[2])
    elif a[:1] == ["cpu"]:
        print(f"{cpu():.1f} %")
    elif a[:1] == ["etat"]:
        etat()
    elif a[:1] == ["migrer"]:
        ecrire_conf(reglages())
        print(f"{CONF} réécrit au format actuel")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
