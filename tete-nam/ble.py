#!/usr/bin/env python3
"""Pont Bluetooth (BLE) de la Tête NAM, pour l'appli Android.

L'appli parle à ce service en Bluetooth Low Energy ; ce service transmet
chaque demande à la page web locale (http://127.0.0.1:8080/api/...). Toute
la logique (mod-host, sauvegarde dans /etc/tete-nam.conf) reste donc dans
web.py : la page et l'appli voient et changent exactement la même chose.

Protocole (un service GATT, trois caractéristiques) :
  COMMANDE (écriture)    l'appli écrit une ligne JSON terminée par "\\n",
                         éventuellement en plusieurs morceaux :
                         {"n": 12, "op": "etat", "leger": true}
  REPONSE  (notification) la réponse JSON, terminée par "\\n", découpée en
                         morceaux de la taille du MTU : {"n": 12, ...}
  FICHIER  (écriture)    octets bruts d'un fichier .nam, entre
                         {"op": "envoi_debut", "nom": ...} et {"op": "envoi_fin"}

Opérations : etat (leger = sans graphe ni liste de modèles), modele, niveau,
actif, mode, calibration, buffer (mêmes champs que la page web),
envoi_debut, envoi_fin.

Dépendances : python3-dbus et python3-gi (paquets Debian, posés par install.sh).
"""
import hashlib
import json
import os
import queue
import sys
import threading
import urllib.error
import urllib.request

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

NOM = os.environ.get("TETE_NAM_BLE_NOM", "TeteNAM")
WEB = "http://127.0.0.1:%s" % os.environ.get("TETE_NAM_PORT", "8080")

# "tete" "na" "m-ble1" en hexadécimal : les mêmes UUID que dans l'appli
UUID_SERVICE = "7e7e0001-7465-7465-6e61-6d2d626c6531"
UUID_COMMANDE = "7e7e0002-7465-7465-6e61-6d2d626c6531"
UUID_REPONSE = "7e7e0003-7465-7465-6e61-6d2d626c6531"
UUID_FICHIER = "7e7e0004-7465-7465-6e61-6d2d626c6531"

BLUEZ = "org.bluez"
GATT_MANAGER = "org.bluez.GattManager1"
ADV_MANAGER = "org.bluez.LEAdvertisingManager1"
OBJ_MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPS = "org.freedesktop.DBus.Properties"
TAILLE_MAX = 50 * 1024 * 1024
ROUTES = ("modele", "niveau", "actif", "mode", "calibration", "buffer")


def journal(*a):
    print(*a, flush=True)


# --- Transmission à la page web (dans un fil à part : jamais de blocage BLE) --

def http(chemin, corps=None, entetes=None, delai=15):
    req = urllib.request.Request(WEB + chemin, data=corps, headers=entetes or {},
                                 method="POST" if corps is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "erreur": f"Page web de la tête injoignable ({e})"}


def signature(liste):
    return hashlib.md5("\n".join(liste).encode()).hexdigest()[:10]


class Pont:
    """Reçoit les commandes de l'appli, répond via la caractéristique REPONSE."""

    def __init__(self):
        self.entree = bytearray()       # ligne de commande en cours de réception
        self.fichier = None             # bytearray pendant un envoi de fichier
        self.nom_fichier = ""
        self.mtu = 23
        self.reponse = None             # caractéristique REPONSE (pour notifier)
        self.travail = queue.Queue()
        threading.Thread(target=self.boucle, daemon=True).start()

    # Appelé depuis la boucle D-Bus
    def recu_commande(self, octets, mtu):
        if mtu:
            self.mtu = mtu
        self.entree += octets
        while b"\n" in self.entree:
            ligne, _, reste = bytes(self.entree).partition(b"\n")
            self.entree = bytearray(reste)
            if ligne.strip():
                self.travail.put(ligne)

    def recu_fichier(self, octets, mtu):
        if mtu:
            self.mtu = mtu
        if self.fichier is None:
            return
        if len(self.fichier) + len(octets) > TAILLE_MAX:
            self.fichier = None
            return
        self.fichier += octets

    def boucle(self):
        while True:
            ligne = self.travail.get()
            n = None
            try:
                d = json.loads(ligne)
                n = d.get("n")
                r = self.traiter(d)
            except Exception as e:      # on renvoie l'erreur à l'appli
                r = {"ok": False, "erreur": str(e)}
            r["n"] = n
            self.envoyer(json.dumps(r, separators=(",", ":")).encode() + b"\n")

    def traiter(self, d):
        op = d.get("op")
        if op == "bonjour":
            if d.get("mtu"):
                self.mtu = max(23, min(517, int(d["mtu"])))
            return {"ok": True, "nom": NOM, "version": 1}
        if op == "etat":
            e = http("/api/etat", delai=5)
            if "disponibles" in e:
                e["sig"] = signature(e["disponibles"])
                if d.get("leger"):
                    del e["disponibles"]
                    e["histo"] = []
            return e
        if op in ROUTES:
            params = {k: v for k, v in d.items() if k not in ("n", "op")}
            return http("/api/" + op, json.dumps(params).encode(),
                        {"Content-Type": "application/json"})
        if op == "envoi_debut":
            self.nom_fichier = str(d.get("nom", ""))
            self.fichier = bytearray()
            return {"ok": True}
        if op == "envoi_fin":
            if self.fichier is None:
                return {"ok": False, "erreur": "Envoi interrompu (ou fichier trop gros)"}
            contenu, self.fichier = bytes(self.fichier), None
            attendu = d.get("taille")
            if attendu is not None and int(attendu) != len(contenu):
                return {"ok": False, "erreur": f"Fichier incomplet ({len(contenu)} octets "
                        f"reçus sur {attendu}), réessayez"}
            return http("/api/envoyer", contenu,
                        {"X-Nom-Fichier": urllib.request.quote(self.nom_fichier),
                         "Content-Type": "application/octet-stream"}, delai=60)
        return {"ok": False, "erreur": f"Opération inconnue : {op}"}

    def envoyer(self, octets):
        taille = max(20, self.mtu - 3)
        morceaux = [octets[i:i + taille] for i in range(0, len(octets), taille)]
        GLib.idle_add(self._notifier, morceaux)

    def _notifier(self, morceaux):
        if self.reponse is not None:
            for m in morceaux:
                self.reponse.notifier(m)
        return False


# --- Objets GATT exposés à BlueZ (schéma de l'exemple officiel de BlueZ) -----

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.chemin = "/tetenam"
        self.services = []
        super().__init__(bus, self.chemin)

    @dbus.service.method(OBJ_MANAGER, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        rep = {}
        for s in self.services:
            rep[s.get_path()] = s.proprietes()
            for c in s.caracs:
                rep[c.get_path()] = c.proprietes()
        return rep

    def get_path(self):
        return dbus.ObjectPath(self.chemin)


class Service(dbus.service.Object):
    def __init__(self, bus, index, uuid):
        self.chemin = f"/tetenam/service{index}"
        self.uuid = uuid
        self.caracs = []
        super().__init__(bus, self.chemin)

    def get_path(self):
        return dbus.ObjectPath(self.chemin)

    def proprietes(self):
        return {"org.bluez.GattService1": {
            "UUID": self.uuid, "Primary": True,
            "Characteristics": dbus.Array([c.get_path() for c in self.caracs], signature="o")}}

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.proprietes()["org.bluez.GattService1"]


class Carac(dbus.service.Object):
    IFACE = "org.bluez.GattCharacteristic1"

    def __init__(self, bus, index, uuid, drapeaux, service, recevoir=None):
        self.chemin = f"{service.chemin}/char{index}"
        self.uuid, self.drapeaux, self.service = uuid, drapeaux, service
        self.recevoir = recevoir
        self.abonne = False
        super().__init__(bus, self.chemin)

    def get_path(self):
        return dbus.ObjectPath(self.chemin)

    def proprietes(self):
        return {self.IFACE: {"Service": self.service.get_path(), "UUID": self.uuid,
                             "Flags": dbus.Array(self.drapeaux, signature="s")}}

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.proprietes()[self.IFACE]

    @dbus.service.method(IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return dbus.Array([], signature="y")

    @dbus.service.method(IFACE, in_signature="aya{sv}")
    def WriteValue(self, valeur, options):
        if self.recevoir:
            self.recevoir(bytes(valeur), int(options.get("mtu", 0)))

    @dbus.service.method(IFACE)
    def StartNotify(self):
        self.abonne = True
        journal("Appli connectée (notifications activées)")

    @dbus.service.method(IFACE)
    def StopNotify(self):
        self.abonne = False
        journal("Appli déconnectée")

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changees, invalidees):
        pass

    def notifier(self, octets):
        if self.abonne:
            self.PropertiesChanged(self.IFACE, {"Value": dbus.Array(octets, signature="y")}, [])


class Annonce(dbus.service.Object):
    """Publicité BLE : l'appli trouve la tête par l'UUID du service."""
    IFACE = "org.bluez.LEAdvertisement1"

    def __init__(self, bus):
        self.chemin = "/tetenam/annonce0"
        super().__init__(bus, self.chemin)

    def get_path(self):
        return dbus.ObjectPath(self.chemin)

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return {"Type": "peripheral",
                "ServiceUUIDs": dbus.Array([UUID_SERVICE], signature="s"),
                "LocalName": dbus.String(NOM)}

    @dbus.service.method(IFACE)
    def Release(self):
        pass


def trouver_adaptateur(bus):
    om = dbus.Interface(bus.get_object(BLUEZ, "/"), OBJ_MANAGER)
    for chemin, ifaces in om.GetManagedObjects().items():
        if GATT_MANAGER in ifaces and ADV_MANAGER in ifaces:
            return chemin
    return None


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    boucle = GLib.MainLoop()

    adaptateur = None
    for _ in range(30):                 # le Bluetooth peut mettre un peu à démarrer
        try:
            adaptateur = trouver_adaptateur(bus)
        except dbus.exceptions.DBusException:
            pass
        if adaptateur:
            break
        GLib.usleep(1_000_000)
    if not adaptateur:
        sys.exit("Aucun adaptateur Bluetooth LE trouvé (sudo rfkill unblock bluetooth ?)")

    props = dbus.Interface(bus.get_object(BLUEZ, adaptateur), PROPS)
    props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
    try:
        props.Set("org.bluez.Adapter1", "Alias", dbus.String(NOM))
    except dbus.exceptions.DBusException:
        pass

    pont = Pont()
    app = Application(bus)
    svc = Service(bus, 0, UUID_SERVICE)
    svc.caracs = [
        Carac(bus, 0, UUID_COMMANDE, ["write"], svc, pont.recu_commande),
        Carac(bus, 1, UUID_REPONSE, ["notify"], svc),
        Carac(bus, 2, UUID_FICHIER, ["write", "write-without-response"], svc,
              pont.recu_fichier),
    ]
    pont.reponse = svc.caracs[1]
    app.services = [svc]
    annonce = Annonce(bus)

    gatt = dbus.Interface(bus.get_object(BLUEZ, adaptateur), GATT_MANAGER)
    pub = dbus.Interface(bus.get_object(BLUEZ, adaptateur), ADV_MANAGER)

    def erreur(e):
        journal("ERREUR BlueZ :", e)
        boucle.quit()

    def annoncer():
        """(Re)lance la publicité. Après une déconnexion, certains BlueZ ne
        la relancent pas d'eux-mêmes : on la réenregistre."""
        def ok():
            journal(f"Visible en Bluetooth sous le nom {NOM}")
        try:
            pub.UnregisterAdvertisement(annonce.get_path())
        except dbus.exceptions.DBusException:
            pass
        pub.RegisterAdvertisement(annonce.get_path(), {}, reply_handler=ok,
                                  error_handler=lambda e: journal("Publicité refusée :", e))
        return False

    def appareil_change(iface, changees, invalidees, path=None):
        if iface == "org.bluez.Device1" and changees.get("Connected") is False:
            pont.entree.clear()
            pont.fichier = None
            GLib.timeout_add(1000, annoncer)

    bus.add_signal_receiver(appareil_change, dbus_interface=PROPS,
                            signal_name="PropertiesChanged", path_keyword="path")
    # Si bluetoothd redémarre, on sort : systemd nous relance proprement
    bus.watch_name_owner(BLUEZ, lambda proprio: proprio or boucle.quit())

    gatt.RegisterApplication(app.get_path(), {},
                             reply_handler=lambda: journal("Service Bluetooth prêt"),
                             error_handler=erreur)
    annoncer()
    boucle.run()
    sys.exit(1)


if __name__ == "__main__":
    main()
