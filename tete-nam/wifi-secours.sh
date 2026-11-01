#!/bin/bash
# Wi-Fi de secours de la Tête NAM : si aucun Wi-Fi connu n'est trouvé,
# la tête crée son propre réseau pour joindre la page web depuis un téléphone.
#
#   tete-nam-wifi etat       ce qui est actif en ce moment
#   tete-nam-wifi hotspot    passe sur le réseau de la tête
#   tete-nam-wifi maison     repasse sur le Wi-Fi connu (hotspot si échec)
#   tete-nam-wifi auto       ce que fait le démarrage (service tete-nam-wifi)
set -u

PROFIL=tete-nam-hotspot
IFACE=wlan0
IP=10.42.0.1

MODE=auto; ATTENTE=45; SSID=TeteNAM; MOT_DE_PASSE=tetenam2026; CANAL=6
[ -r /etc/tete-nam-wifi.conf ] && source /etc/tete-nam-wifi.conf

log() { echo "tete-nam-wifi : $*"; }

besoin_root() {
    if [ "$(id -u)" -ne 0 ]; then
        exec sudo "$0" "$@"
    fi
}

# Connexion Wi-Fi active sur wlan0 (vide si aucune)
connexion_active() {
    nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION dev show "$IFACE" 2>/dev/null |
        awk -F: '/^GENERAL.STATE/ {etat=$2} /^GENERAL.CONNECTION/ {c=$2}
                 END { if (etat ~ /^100/) print c }'
}

# Crée ou met à jour le profil hotspot à partir des réglages
preparer_profil() {
    if [ ${#MOT_DE_PASSE} -lt 8 ]; then
        log "ERREUR : MOT_DE_PASSE doit faire au moins 8 caractères (/etc/tete-nam-wifi.conf)"
        exit 1
    fi
    nmcli -t -f NAME con show | grep -qx "$PROFIL" ||
        nmcli con add type wifi ifname "$IFACE" con-name "$PROFIL" ssid "$SSID" >/dev/null
    # proto/pairwise/group en CCMP : nécessaire pour que les téléphones
    # récents acceptent le réseau créé par la puce Wi-Fi du Pi.
    nmcli con modify "$PROFIL" \
        connection.autoconnect no \
        802-11-wireless.ssid "$SSID" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless.channel "$CANAL" \
        802-11-wireless.powersave 2 \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.proto rsn \
        wifi-sec.pairwise ccmp \
        wifi-sec.group ccmp \
        wifi-sec.psk "$MOT_DE_PASSE" \
        ipv4.method shared \
        ipv4.addresses "$IP/24" \
        ipv6.method disabled
}

hotspot() {
    preparer_profil
    log "création du réseau « $SSID » (canal $CANAL)"
    if nmcli con up "$PROFIL" >/dev/null; then
        log "OK. Sur le téléphone : Wi-Fi « $SSID », puis http://tetenam.local:8080"
        log "    (ou http://$IP:8080 si le nom ne marche pas)"
    else
        log "ERREUR : le hotspot n'a pas démarré (journalctl -u NetworkManager -n 30)"
        return 1
    fi
}

maison() {
    log "retour au Wi-Fi connu"
    nmcli con down "$PROFIL" >/dev/null 2>&1
    nmcli dev wifi rescan ifname "$IFACE" >/dev/null 2>&1
    sleep 5
    nmcli dev connect "$IFACE" >/dev/null 2>&1
    for _ in $(seq 1 "$ATTENTE"); do
        c=$(connexion_active)
        if [ -n "$c" ] && [ "$c" != "$PROFIL" ]; then
            log "connecté à « $c »"; return 0
        fi
        sleep 1
    done
    log "aucun Wi-Fi connu trouvé : on remet le hotspot pour ne pas perdre la tête"
    hotspot
}

auto() {
    case "$MODE" in
        hotspot) hotspot; return ;;
        maison)  log "MODE=maison : pas de hotspot"; return 0 ;;
    esac
    log "recherche d'un Wi-Fi connu (${ATTENTE} s max)"
    for _ in $(seq 1 "$ATTENTE"); do
        c=$(connexion_active)
        if [ -n "$c" ] && [ "$c" != "$PROFIL" ]; then
            log "connecté à « $c », pas besoin de hotspot"; return 0
        fi
        sleep 1
    done
    log "aucun Wi-Fi connu"
    hotspot
}

etat() {
    c=$(connexion_active)
    if [ -z "$c" ]; then
        echo "Wi-Fi : aucune connexion"
    elif [ "$c" = "$PROFIL" ]; then
        echo "Wi-Fi : hotspot « $SSID » actif -> http://tetenam.local:8080 ou http://$IP:8080"
    else
        ip4=$(nmcli -g IP4.ADDRESS dev show "$IFACE" | head -1 | cut -d/ -f1)
        echo "Wi-Fi : connecté à « $c » ($ip4) -> http://tetenam.local:8080"
    fi
    echo "Mode au démarrage : $MODE (/etc/tete-nam-wifi.conf)"
}

if ! command -v nmcli >/dev/null; then
    log "ERREUR : NetworkManager absent (nmcli introuvable)"; exit 1
fi
if ! nmcli -t -f DEVICE dev | grep -qx "$IFACE"; then
    log "pas d'interface $IFACE sur cette machine, rien à faire"; exit 0
fi

ACTION=${1:-etat}
case "$ACTION" in
    etat) etat ;;
    auto) besoin_root "$@"; auto ;;
    hotspot|maison)
        besoin_root "$@"
        # Lancé depuis un téléphone ou un SSH branché sur ce même Wi-Fi, la
        # connexion va couper : on fait la bascule en tâche de fond pour
        # qu'elle aille au bout quand même.
        if [ -z "${INVOCATION_ID:-}" ]; then
            log "bascule lancée (la connexion SSH peut couper, c'est normal)"
            exec systemd-run --quiet --collect --unit="tete-nam-wifi-$ACTION" "$0" "$ACTION"
        fi
        "$ACTION" ;;
    *) sed -n '5,8p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
