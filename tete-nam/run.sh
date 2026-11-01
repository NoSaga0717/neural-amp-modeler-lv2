#!/bin/bash
# Lancé par le service systemd "tete-nam" : JACK -> mod-host -> chaîne NAM.
# Si l'un des deux s'arrête, on sort et systemd relance le tout.
set -u
source /etc/tete-nam.conf

# Pas de session D-Bus ici : on évite la réservation de carte par D-Bus
export JACK_NO_AUDIO_RESERVATION=1
export LV2_PATH=/usr/local/lib/lv2:/usr/lib/lv2

echo "Attente de la carte $CARD..."
for i in $(seq 1 30); do
    [ -e "/proc/asound/$CARD" ] && break
    sleep 1
done
if [ ! -e "/proc/asound/$CARD" ]; then
    echo "ERREUR : carte $CARD introuvable. Cartes vues :"
    cat /proc/asound/cards
    exit 1
fi

echo "Démarrage de JACK : hw:$CARD, $RATE Hz, buffer $PERIOD x $NPERIODS"
jackd -R -P 80 -d alsa -d "hw:$CARD" -r "$RATE" -p "$PERIOD" -n "$NPERIODS" &
JACK_PID=$!

if ! jack_wait -w -t 15 >/dev/null; then
    echo "ERREUR : JACK n'a pas démarré"
    exit 1
fi

echo "Démarrage de mod-host"
mod-host -n -p 5555 &
HOST_PID=$!

if ! python3 /opt/tete-nam/tetenam.py charger; then
    echo "ERREUR : la chaîne NAM n'a pas pu être chargée"
    kill "$HOST_PID" "$JACK_PID" 2>/dev/null
    exit 1
fi

# On reste là tant que JACK et mod-host tournent
wait -n "$JACK_PID" "$HOST_PID"
echo "JACK ou mod-host s'est arrêté, redémarrage par systemd"
kill "$HOST_PID" "$JACK_PID" 2>/dev/null
exit 1
