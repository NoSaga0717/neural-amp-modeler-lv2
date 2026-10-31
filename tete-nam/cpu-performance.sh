#!/bin/sh
# Met tous les coeurs en mode "performance" (fréquence max, pas de variations)
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$g" 2>/dev/null || true
done
exit 0
