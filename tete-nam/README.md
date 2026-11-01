# Tête NAM : premier test sur Raspberry Pi 3

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
git clone -b claude/project-thread-wu9p0j https://github.com/nosaga0717/neural-amp-modeler-lv2.git
cd neural-amp-modeler-lv2
sudo ./tete-nam/install.sh
```

Si vous aviez déjà lancé l'installation avant l'arrivée de la page web, mettez à jour avec `cd neural-amp-modeler-lv2 && git pull && sudo ./tete-nam/install.sh` (quelques minutes seulement, la compilation est déjà faite).

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

Elle permet d'envoyer vos fichiers `.nam` sur la tête (bouton en bas de page). Elle gère aussi la chaîne de NAM, branchés en série (entrée → NAM 1 → NAM 2 → NAM 3 → ampli) :

- au démarrage, un NAM est chargé avec la qualité à 0 (le plus léger) ;
- **+ Ajouter un NAM** en ajoute un, jusqu'à 3 ;
- **Activé / Désactivé** laisse passer le son sans traitement. Un NAM désactivé reste chargé et ne consomme presque plus de processeur ;
- **×** retire un NAM ;
- pour chacun : choix du fichier `.nam` dans `~/nam`, qualité A2 de 0 à 1, niveaux d'entrée et de sortie.

Ces changements sont immédiats mais pas sauvegardés : au redémarrage, la tête repart de `/etc/tete-nam.conf`. La page tourne en priorité basse pour ne jamais gêner l'audio. Si elle ne répond pas : `journalctl -u tete-nam-web -n 30`.

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

Changez les réglages avec `sudo nano /etc/tete-nam.conf` (Ctrl+O pour enregistrer, Ctrl+X pour sortir), puis `sudo systemctl restart tete-nam`.

| Étape | Réglage | Ce qu'on regarde |
|---|---|---|
| A | 1 modèle A2, `QUALITY=0.0`, `PERIOD=256` | Ça sonne, charge DSP, 0 xrun sur 5 minutes de jeu |
| B | Idem avec `PERIOD=128` | Idem. La latence doit devenir imperceptible |
| C | `NPERIODS=2` (garder 128) | Encore moins de latence, si toujours 0 xrun |
| D | Monter `QUALITY` par pas de 0.1 (curseur de la page web) | Jusqu'où le Pi 3 tient : noter la valeur où la charge passe 85 % |
| E | 2 modèles : remplir `MODEL2=` | Test de charge (les deux modèles sont en série) |

Notez à chaque étape la charge DSP et les xruns. Repères :

- **Charge DSP** sous 70 % : confortable. Au-delà de 85 %, ça finira par craquer.
- **Xruns** : 0 en jouant 5 minutes. Le compteur repart à zéro à chaque redémarrage du service.
- **Température** sous 80 °C. Au-delà, le Pi ralentit : mettez un dissipateur, voire un petit ventilateur.
- **Throttling** `0x0`. Autre chose = alimentation trop faible (prenez l'alim officielle 2,5 A, la M4 tire sur l'USB du Pi) ou surchauffe.

Pour essayer un autre modèle sans redémarrer (ou depuis la page web) :

```bash
tete-nam modele 1 ~/nam/autre_modele.nam
```

## Réglages (`/etc/tete-nam.conf`)

| Réglage | Rôle |
|---|---|
| `CARD` | Nom de la carte son (`cat /proc/asound/cards` pour le vérifier) |
| `RATE` | 48000, comme les modèles |
| `PERIOD`, `NPERIODS` | Taille et nombre de buffers JACK |
| `INPUT`, `OUTPUTS` | Entrée guitare et sorties de la M4 |
| `MODEL1`, `MODEL2` | Chemins des modèles `.nam` |
| `IN_DB`, `OUT_DB` | Niveau avant et après le modèle, en dB |
| `QUALITY` | Taille du modèle NAM A2 qui tourne : 0.0 = la plus légère, 1.0 = complète |

## Si ça ne marche pas

- `tete-nam etat` dit *inactive* ou *activating* : regardez `journalctl -u tete-nam -n 50`. Les messages commencent par ERREUR et disent quoi faire (carte introuvable, modèle introuvable…).
- **Carte introuvable** : `cat /proc/asound/cards`, puis mettez dans `CARD=` le nom entre crochets de la M4.
- **Pas de son mais tout est actif** : vérifiez le bouton MONITOR de la M4, le câble vers FX RETURN et `jack_lsp -c` (les connexions doivent aller de `system:capture_1` à `effect_0`, puis vers `system:playback_1`).
- **Annuler les réglages de démarrage** : une copie de `cmdline.txt` d'origine est dans `/boot/firmware/cmdline.txt.avant-tete-nam`.
- **Couper le démarrage automatique** : `sudo systemctl disable --now tete-nam`.
- **Le réseau TeteNAM n'apparaît pas** : `journalctl -u tete-nam-wifi -n 30`. Vérifiez que le pays Wi-Fi est réglé (`sudo raspi-config`, *Localisation Options*, *WLAN Country*, FR).
