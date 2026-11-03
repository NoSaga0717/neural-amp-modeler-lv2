# Tête NAM : premier test sur Raspberry Pi 3

> **Plus utilisé (3 novembre 2026)** : la Tête NAM est passée sur Raspberry Pi 5 avec le moteur stompbox. Le logiciel est maintenant dans [`NoSaga0717/stompbox`](https://github.com/NoSaga0717/stompbox), dossier `tete-nam/`. Ce dossier reste pour l'historique de la version Pi 3 (mod-host + plugin NAM LV2).

Montage : guitare → MOTU M4 (entrée 1, instrument) → Pi 3 (USB) → M4 sortie 1 → FX RETURN de la Spider Valve → 4x12.

Logiciel : Raspberry Pi OS Lite 64 bits, JACK (serveur audio temps réel), mod-host (hôte de plugins piloté par le réseau, le même que les pédaliers MOD), et le plugin `neural-amp-modeler-lv2` de ce dépôt. Tout démarre tout seul à l'allumage.

## 1. Préparer la carte SD (sur votre ordinateur)

1. Installez **Raspberry Pi Imager** : https://www.raspberrypi.com/software/
2. **Appareil** : Raspberry Pi 3.
3. **Système** : *Raspberry Pi OS (other)* → **Raspberry Pi OS Lite (64-bit)**. Lite = sans bureau, c'est voulu.
4. **Stockage** : votre carte SD (16 Go ou plus, classe A1 de préférence).
5. Quand Imager propose la **personnalisation**, remplissez :
   - nom d'hôte : `tetenam`
   - utilisateur et mot de passe (par exemple `alex`)
   - Wi-Fi : nom du réseau, mot de passe, pays **FR**
   - fuseau horaire Europe/Paris, clavier `fr`
   - **SSH activé**, avec authentification par mot de passe
6. Écrivez la carte, mettez-la dans le Pi, branchez l'alim. Le premier démarrage prend 2 à 3 minutes.

> Sur le Pi 3, la prise Ethernet partage le même bus USB que la M4. Préférez le Wi-Fi pour vous connecter pendant les tests.

## 2. Se connecter au Pi

Depuis un terminal (Windows : PowerShell, Mac/Linux : Terminal) :

```bash
ssh alex@tetenam.local
```

(Remplacez `alex` par votre utilisateur. Si `tetenam.local` ne répond pas, cherchez l'adresse IP du Pi sur votre box.)

## 3. Installer (copier-coller, une ligne à la fois)

Branchez la M4 sur un port USB du Pi avant de commencer.

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/NoSaga0717/neural-amp-modeler-lv2.git
cd neural-amp-modeler-lv2
sudo ./tete-nam/install.sh
```

Pour mettre à jour une installation existante : `cd neural-amp-modeler-lv2 && git pull && sudo ./tete-nam/install.sh`. Si `git pull` se plaint d'une branche introuvable (première installation faite depuis l'ancienne branche de travail), tapez d'abord `git fetch origin && git checkout main`.

Le script installe JACK, le plugin NAM et mod-host, règle le temps réel et le démarrage automatique. **Comptez 10 à 20 minutes sur un Pi 3**, surtout pour télécharger et installer les paquets.

Le plugin NAM est livré **précompilé** dans `tete-nam/precompile/` (pour Raspberry Pi OS 64 bits, Bookworm ou Trixie) : le script l'utilise s'il correspond exactement aux sources du dépôt, sinon il le compile sur le Pi (35 à 50 minutes de plus sur un Pi 3). Pour forcer la compilation sur le Pi : `sudo ./tete-nam/install.sh --compiler`. Pour refaire la version précompilée sur un PC Linux, voir `tete-nam/precompile/construire.sh`.

Si la connexion SSH coupe pendant l'installation, reconnectez-vous et tapez `cd neural-amp-modeler-lv2 && sudo ./tete-nam/install.sh` : le script reprend là où il en était.

## 4. Copier le modèle

Le plus simple, une fois la tête démarrée : ouvrez **http://tetenam.local:8080** et utilisez le bouton **Envoyer des fichiers .nam vers la tête** en bas de la page. Vous pouvez en envoyer plusieurs d'un coup, depuis un ordinateur ou un téléphone. Les espaces dans les noms sont remplacés par des `_`.

Sinon, en ligne de commande :

Depuis votre ordinateur (pas depuis le Pi), dans le dossier où se trouve votre fichier `.nam` :

```bash
scp mon_modele_lite.nam alex@tetenam.local:~/nam/modele1.nam
```

Pour garder le nom d'origine, copiez-le tel quel et indiquez son chemin dans les réglages (voir plus bas). Évitez les espaces dans les noms de fichiers.

Puis, sur le Pi :

```bash
sudo reboot
```

## 5. Premier son

**Avant d'allumer** : le 4x12 est branché sur la sortie HP de la Spider Valve (jamais de tête à lampes sans charge), le bouton MONITOR de la M4 est au minimum et le master de la Spider Valve est bas.

1. Guitare dans l'entrée combo 1 de la M4, en jack 6,35 (entrée haute impédance, passive ou active). Réglez le gain 1 pour que le vu-mètre de l'écran ne touche jamais le rouge en jouant fort.
2. Sortie **MONITOR OUT L** de la M4 (sortie 1, à l'arrière) → **FX RETURN** de la Spider Valve.
3. Allumez le Pi, attendez environ 40 secondes, puis montez doucement le MONITOR de la M4, puis le master de l'ampli.

## 6. Vérifier que tout va bien

```bash
tete-nam etat
```

Affiche : service actif, charge DSP, nombre de xruns (craquements), température, throttling et réglages. Pour suivre en direct pendant que vous jouez :

```bash
watch -n 1 tete-nam etat
```

(Ctrl+C pour sortir.) Le journal complet : `journalctl -u tete-nam -f`.

### Ou depuis un navigateur

Sur un téléphone ou un ordinateur connecté au même Wi-Fi, ouvrez **http://tetenam.local:8080**. La page affiche en direct la charge DSP (avec un graphe des 2 dernières minutes), les xruns, la température et le throttling.

Elle permet d'envoyer vos fichiers `.nam` sur la tête (bouton en bas de page) et de tout régler :

- **Buffer JACK** : 64, 128, 256 ou 512, toujours avec 2 périodes. La latence correspondante est affichée. **Appliquer** relance l'audio (environ 5 secondes de silence).
- **Calibration d'entrée** : le niveau en dBu qui donne 0 dBFS sur l'entrée de la carte son (16 dBu pour la M4). Une seule valeur pour la tête, appliquée aux deux NAM. Elle ne compte que si le modèle indique son niveau d'entrée (champ `input_level_dbu` des captures récentes).
- **La chaîne**, fixe : entrée → **Pédale** → **Ampli** → power amp. Pour chacun des deux blocs :
  - **Activé / Désactivé** laisse passer le son sans traitement. Un bloc désactivé reste chargé et ne consomme presque plus de processeur ;
  - le fichier `.nam` (la pédale peut rester sans modèle : « aucune pédale ») ;
  - l'**output mode**, comme dans le plugin NAM : **Calibrated** (par défaut pour la pédale : elle sort au même niveau que la vraie pédale, l'ampli la reçoit donc comme en vrai) ou **Normalized** (par défaut pour l'ampli : tous les modèles sortent au même volume) ;
  - la qualité A2 de 0 à 1, les niveaux d'entrée et de sortie.

Chaque changement est appliqué tout de suite et **sauvegardé** dans `/etc/tete-nam.conf` : la tête redémarre comme vous l'avez laissée. La page tourne en priorité basse pour ne jamais gêner l'audio. Si elle ne répond pas : `journalctl -u tete-nam-web -n 30`.

### Sans Wi-Fi (studio) : le réseau de la tête

Au démarrage, la tête attend jusqu'à 45 secondes un Wi-Fi qu'elle connaît (celui entré dans Raspberry Pi Imager). Si elle n'en trouve aucun, elle crée **son propre réseau Wi-Fi** :

1. Sur le téléphone, connectez-vous au Wi-Fi **TeteNAM** (mot de passe `tetenam2026` par défaut, à changer).
2. Ouvrez **http://tetenam.local:8080**, même port que d'habitude. Si le nom ne répond pas (certains Android anciens), ouvrez **http://10.42.0.1:8080**.
3. En SSH : `ssh alex@10.42.0.1`.

Le téléphone dira peut-être « pas d'accès Internet » : c'est normal, restez connecté quand même (sur Android, répondez « garder la connexion »).

Changer le nom, le mot de passe ou le comportement : `sudo nano /etc/tete-nam-wifi.conf`.

| Réglage | Rôle |
|---|---|
| `MODE` | `auto` (Wi-Fi connu sinon hotspot), `hotspot` (toujours le réseau de la tête), `maison` (jamais de hotspot) |
| `ATTENTE` | Secondes laissées au Wi-Fi connu au démarrage |
| `SSID`, `MOT_DE_PASSE` | Nom et mot de passe du réseau de la tête (8 caractères minimum) |
| `CANAL` | 1, 6 ou 11. Changer si un autre réseau gêne |

Commandes :

```bash
tete-nam-wifi etat      # ce qui est actif et l'adresse de la page
tete-nam-wifi hotspot   # passer tout de suite sur le réseau de la tête
tete-nam-wifi maison    # revenir au Wi-Fi connu (s'il est introuvable, le hotspot revient tout seul)
```

Une bascule coupe le Wi-Fi quelques secondes : reconnectez le téléphone au bon réseau. Le hotspot ne touche pas à l'audio et coûte très peu de processeur (c'est la puce Wi-Fi qui fait le travail).

## 7. Procédure de test

Tout se règle depuis la page web. À la main, c'est aussi possible : `sudo nano /etc/tete-nam.conf` (Ctrl+O pour enregistrer, Ctrl+X pour sortir), puis `sudo systemctl restart tete-nam`.

| Étape | Réglage | Ce qu'on regarde |
|---|---|---|
| A | Ampli seul (pédale désactivée), qualité 0, buffer 256 | Ça sonne, charge DSP, 0 xrun sur 5 minutes de jeu |
| B | Buffer 128 | Idem. La latence doit devenir imperceptible |
| C | Buffer 64 | Encore moins de latence, si toujours 0 xrun |
| D | Monter la qualité par pas de 0.1 | Jusqu'où le Pi 3 tient : noter la valeur où la charge passe 85 % |
| E | Activer la pédale | Test de charge (les deux modèles sont en série) |

Notez à chaque étape la charge DSP et les xruns. Repères :

- **Charge DSP** sous 70 % : confortable. Au-delà de 85 %, ça finira par craquer.
- **Xruns** : 0 en jouant 5 minutes. Le compteur repart à zéro à chaque redémarrage du service.
- **Température** sous 80 °C. Au-delà, le Pi ralentit : mettez un dissipateur, voire un petit ventilateur.
- **Throttling** `0x0`. Autre chose = alimentation trop faible (prenez l'alim officielle 2,5 A, la M4 tire sur l'USB du Pi) ou surchauffe.

Pour essayer un autre modèle sans redémarrer (ou depuis la page web) :

```bash
tete-nam modele ampli ~/nam/autre_modele.nam     # ou : tete-nam modele pedale ...
```

## Appli Android (Bluetooth)

Pour régler la tête sans Wi-Fi : l'appli Android **Tête NAM** se connecte en Bluetooth Low Energy et propose les mêmes réglages que la page web (mesures, buffer, calibration, chaîne Pédale → Ampli, envoi de fichiers .nam). La page web et le Wi-Fi restent disponibles : les deux voient et changent exactement les mêmes réglages.

1. Sur le Pi : `cd neural-amp-modeler-lv2 && git pull && sudo ./tete-nam/install.sh` (installe le service `tete-nam-ble`).
2. Sur le téléphone, ouvrez https://github.com/NoSaga0717/neural-amp-modeler-lv2/releases/tag/appli-android et touchez **TeteNAM.apk**. Android demande d'autoriser l'installation depuis le navigateur : acceptez (une seule fois).
3. Ouvrez l'appli, acceptez l'autorisation « Appareils à proximité ». Elle trouve la tête toute seule (nom Bluetooth `TeteNAM`), aucun appairage à faire.

Pour mettre l'appli à jour, retéléchargez le même lien : la nouvelle version s'installe par-dessus. L'APK est reconstruit automatiquement par GitHub à chaque modification de `tete-nam/android/`.

- Journal du pont Bluetooth : `journalctl -u tete-nam-ble -f` (« Visible en Bluetooth sous le nom TeteNAM », puis « Appli connectée »).
- Une seule appli connectée à la fois. Portée : une dizaine de mètres.
- L'envoi de fichiers .nam en Bluetooth est lent (environ une minute par Mo) : pour beaucoup de modèles, la page web en Wi-Fi reste plus rapide.
- Android 11 et moins : la localisation du téléphone doit être activée pour que la recherche Bluetooth marche (exigence d'Android).
- Le pont ne fait que transmettre à la page web locale : si la page web est arrêtée (`systemctl status tete-nam-web`), l'appli affiche « Page web de la tête injoignable ».

## Réglages (`/etc/tete-nam.conf`)

| Réglage | Rôle |
|---|---|
| `CARD` | Nom de la carte son (`cat /proc/asound/cards` pour le vérifier) |
| `RATE` | 48000, comme les modèles |
| `PERIOD`, `NPERIODS` | Taille (64 à 512) et nombre (2) de buffers JACK |
| `INPUT`, `OUTPUTS` | Entrée guitare et sorties de la M4 |
| `INPUT_DBU` | Calibration d'entrée : dBu pour 0 dBFS (16 pour la M4) |
| `PEDALE_MODEL`, `AMPLI_MODEL` | Chemins des modèles `.nam` (pédale : vide = aucune) |
| `..._ACTIF` | 1 = activé, 0 = le son passe sans traitement |
| `..._MODE` | Output mode : `calibrated` ou `normalized` |
| `..._IN_DB`, `..._OUT_DB` | Niveau avant et après le modèle, en dB |
| `..._QUALITY` | Taille du modèle NAM A2 qui tourne : 0.0 = la plus légère, 1.0 = complète |

Une ancienne conf (`MODEL1`, `MODEL2`...) est convertie automatiquement par `install.sh` (copie gardée dans `/etc/tete-nam.conf.avant-chaine-fixe`) : `MODEL1` seul devient l'ampli, `MODEL1` + `MODEL2` deviennent la pédale puis l'ampli.

## Si ça ne marche pas

- `tete-nam etat` dit *inactive* ou *activating* : regardez `journalctl -u tete-nam -n 50`. Les messages commencent par ERREUR et disent quoi faire (carte introuvable, modèle introuvable…).
- **Carte introuvable** : `cat /proc/asound/cards`, puis mettez dans `CARD=` le nom entre crochets de la M4.
- **Pas de son mais tout est actif** : vérifiez le bouton MONITOR de la M4, le câble vers FX RETURN et `jack_lsp -c` (les connexions doivent aller de `system:capture_1` à `effect_0` (la pédale), puis `effect_1` (l'ampli), puis vers `system:playback_1`).
- **Annuler les réglages de démarrage** : une copie de `cmdline.txt` d'origine est dans `/boot/firmware/cmdline.txt.avant-tete-nam`.
- **Couper le démarrage automatique** : `sudo systemctl disable --now tete-nam`.
- **Le réseau TeteNAM n'apparaît pas** : `journalctl -u tete-nam-wifi -n 30`. Vérifiez que le pays Wi-Fi est réglé (`sudo raspi-config`, *Localisation Options*, *WLAN Country*, FR).
