#!/bin/bash
# Installation de la Tête NAM sur Raspberry Pi OS Lite 64 bits.
# Usage (depuis le dossier du dépôt cloné) :  sudo ./tete-nam/install.sh
# Pour forcer la compilation du plugin sur le Pi :  sudo ./tete-nam/install.sh --compiler
set -euo pipefail

# Version de mod-host testée (dépôt moddevices/mod-host)
MOD_HOST_COMMIT=12335c2653740be7fe9ce5b4e017f4086bd5c071

etape() { echo; echo "=== $* ==="; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Lancez ce script avec sudo :  sudo ./tete-nam/install.sh"; exit 1
fi
UTIL="${SUDO_USER:-}"
if [ -z "$UTIL" ] || [ "$UTIL" = root ]; then
    echo "Lancez ce script avec sudo depuis votre utilisateur normal (pas root)"; exit 1
fi
MAISON=$(getent passwd "$UTIL" | cut -d: -f6)
DEPOT=$(cd "$(dirname "$0")/.." && pwd)
ICI="$DEPOT/tete-nam"
[ "$(uname -m)" = aarch64 ] || echo "ATTENTION : système non 64 bits ($(uname -m)), prévu pour aarch64"

etape "1/7 Paquets (JACK, outils de compilation)"
echo "jackd2 jackd/tweak_rt_limits boolean true" | debconf-set-selections
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git build-essential cmake pkg-config python3 \
    jackd2 libjack-jackd2-dev liblilv-dev lilv-utils libreadline-dev libfftw3-dev

etape "2/7 Plugin NAM : version précompilée ou compilation"
sudo -u "$UTIL" git -C "$DEPOT" submodule update --init --recursive
PRECOMP="$ICI/precompile"
if [ "${1:-}" != "--compiler" ] && [ "$(uname -m)" = aarch64 ] \
   && [ -f "$PRECOMP/neural_amp_modeler.lv2-aarch64.tar.gz" ] \
   && [ "$(sudo -u "$UTIL" "$PRECOMP/signature.sh")" = "$(cat "$PRECOMP/signature.txt" 2>/dev/null)" ]; then
    echo "Version précompilée à jour trouvée : pas de compilation (quelques secondes)"
    rm -rf /usr/local/lib/lv2/neural_amp_modeler.lv2
    install -d /usr/local/lib/lv2
    tar -C /usr/local/lib/lv2 -xzf "$PRECOMP/neural_amp_modeler.lv2-aarch64.tar.gz"
else
    echo "Pas de version précompilée à jour : compilation sur le Pi"
    etape "3/7 Compilation du plugin NAM (35 à 50 min sur Pi 3)"
    # Swap temporaire : le Pi 3 n'a que 1 Go de RAM pour compiler
    SWAP=/var/tmp/tete-nam.swap
    if [ ! -e "$SWAP" ]; then
        fallocate -l 2G "$SWAP" && chmod 600 "$SWAP" && mkswap "$SWAP" >/dev/null
    fi
    swapon "$SWAP" 2>/dev/null || true
    trap 'swapoff '"$SWAP"' 2>/dev/null; rm -f '"$SWAP" EXIT
    sudo -u "$UTIL" mkdir -p "$DEPOT/build"
    sudo -u "$UTIL" cmake -S "$DEPOT" -B "$DEPOT/build" -DCMAKE_BUILD_TYPE=Release -DSMART_BYPASS_ENABLED=ON
    sudo -u "$UTIL" cmake --build "$DEPOT/build" -j2
    cmake --install "$DEPOT/build"     # -> /usr/local/lib/lv2/neural_amp_modeler.lv2
fi

etape "4/7 Compilation de l'hôte mod-host"
SRC="$MAISON/src/mod-host"
if [ ! -d "$SRC/.git" ]; then
    sudo -u "$UTIL" git clone https://github.com/moddevices/mod-host.git "$SRC"
fi
sudo -u "$UTIL" git -C "$SRC" fetch -q origin
sudo -u "$UTIL" git -C "$SRC" checkout -q "$MOD_HOST_COMMIT"
sudo -u "$UTIL" make -C "$SRC" -j2
make -C "$SRC" install PREFIX=/usr/local

if ! LV2_PATH=/usr/local/lib/lv2 lv2ls | grep -q neural-amp-modeler-lv2; then
    echo "ERREUR : le plugin NAM n'est pas vu par LV2"; exit 1
fi

etape "5/7 Fichiers de la Tête NAM"
install -d /opt/tete-nam
install -m 755 "$ICI/run.sh" "$ICI/cpu-performance.sh" "$ICI/tetenam.py" "$ICI/web.py" \
    "$ICI/wifi-secours.sh" /opt/tete-nam/
ln -sf /opt/tete-nam/tetenam.py /usr/local/bin/tete-nam
ln -sf /opt/tete-nam/wifi-secours.sh /usr/local/bin/tete-nam-wifi
if [ ! -e /etc/tete-nam-wifi.conf ]; then
    install -m 644 "$ICI/tete-nam-wifi.conf" /etc/tete-nam-wifi.conf
    echo "Réglages Wi-Fi de secours créés : /etc/tete-nam-wifi.conf"
fi
if [ ! -e /etc/tete-nam.conf ]; then
    sed "s#__HOME__#$MAISON#" "$ICI/tete-nam.conf" > /etc/tete-nam.conf
    echo "Réglages créés : /etc/tete-nam.conf"
else
    echo "Réglages existants gardés : /etc/tete-nam.conf"
fi
sudo -u "$UTIL" mkdir -p "$MAISON/nam"

etape "6/7 Réglages temps réel"
usermod -aG audio,systemd-journal "$UTIL"
cat > /etc/security/limits.d/95-tete-nam.conf <<EOF
@audio - rtprio 95
@audio - memlock unlimited
EOF
# threadirqs : meilleure priorité pour l'USB audio
# usbcore.autosuspend=-1 : pas de mise en veille de la M4
CMDLINE=/boot/firmware/cmdline.txt
[ -e "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
[ -e "$CMDLINE.avant-tete-nam" ] || cp "$CMDLINE" "$CMDLINE.avant-tete-nam"
for opt in threadirqs usbcore.autosuspend=-1; do
    grep -qw -- "$opt" "$CMDLINE" || sed -i "1 s/\$/ $opt/" "$CMDLINE"
done

etape "7/7 Démarrage automatique"
for svc in tete-nam tete-nam-web; do
    sed "s/__USER__/$UTIL/" "$ICI/$svc.service" > "/etc/systemd/system/$svc.service"
done
install -m 644 "$ICI/tete-nam-wifi.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable tete-nam.service tete-nam-web.service tete-nam-wifi.service
systemctl restart tete-nam-web.service || true

echo
echo "Installation terminée."
echo "1. Copiez votre modèle dans $MAISON/nam/ (nom : modele1.nam, ou changez MODEL1"
echo "   dans /etc/tete-nam.conf avec : sudo nano /etc/tete-nam.conf)"
echo "2. Redémarrez :  sudo reboot"
echo "3. Vérifiez   :  tete-nam etat"
echo "   ou dans un navigateur : http://$(hostname).local:8080"
echo "Sans Wi-Fi connu, la tête crée son propre réseau : voir /etc/tete-nam-wifi.conf"
echo "(nom et mot de passe à changer) et tete-nam-wifi etat"
