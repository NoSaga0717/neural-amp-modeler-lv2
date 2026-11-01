#!/usr/bin/env python3
"""Petit outil de pilotage de la Tête NAM (parle à mod-host sur le port 5555).

  tete-nam charger            charge la chaîne décrite dans /etc/tete-nam.conf
  tete-nam modele 1 FICHIER   change le modèle 1 (ou 2) à chaud
  tete-nam cpu                affiche la charge DSP de JACK
  tete-nam etat               résumé : service, DSP, xruns, température
"""
import shlex
import socket
import subprocess
import sys
import time

CONF = "/etc/tete-nam.conf"
HOST, PORT = "127.0.0.1", 5555
PLUGIN = "http://github.com/mikeoliphant/neural-amp-modeler-lv2"
MODEL_PROP = PLUGIN + "#model"


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


def charger():
    c = lire_conf()
    modeles = [m for m in (c.get("MODEL1", ""), c.get("MODEL2", "")) if m]
    if not modeles:
        sys.exit("Aucun modèle dans /etc/tete-nam.conf (MODEL1)")
    mh = ModHost()
    for i, chemin in enumerate(modeles):
        try:
            open(chemin, "rb").close()
        except OSError:
            sys.exit(f"Fichier modèle introuvable : {chemin}")
        mh.cmd(f"add {q(PLUGIN)} {i}")
        mh.cmd(f"param_set {i} input_level {c.get('IN_DB', '0')}")
        mh.cmd(f"param_set {i} output_level {c.get('OUT_DB', '0')}")
        mh.cmd(f"param_set {i} quality_scale {c.get('QUALITY', '0.0')}")
        mh.cmd(f"patch_set {i} {q(MODEL_PROP)} {q(chemin)}")
        print(f"Modèle {i + 1} chargé : {chemin}")
    # Câblage : entrée -> modèle 1 -> (modèle 2) -> sorties
    mh.cmd(f"connect {q(c.get('INPUT', 'system:capture_1'))} effect_0:input")
    for i in range(1, len(modeles)):
        mh.cmd(f"connect effect_{i - 1}:output effect_{i}:input")
    dernier = f"effect_{len(modeles) - 1}:output"
    for sortie in c.get("OUTPUTS", "system:playback_1").split():
        mh.cmd(f"connect {dernier} {q(sortie)}")
    print("Chaîne prête.")


def changer_modele(num, chemin):
    open(chemin, "rb").close()
    rep = ModHost(attente=2).cmd(f"patch_set {int(num) - 1} {q(MODEL_PROP)} {q(chemin)}")
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
    c = lire_conf()
    print(f"Réglages     : {c.get('RATE')} Hz, buffer {c.get('PERIOD')} x {c.get('NPERIODS')}")
    print("Modèles      :", c.get("MODEL1"), c.get("MODEL2") or "")


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
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
