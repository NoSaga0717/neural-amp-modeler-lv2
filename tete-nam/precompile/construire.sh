#!/bin/bash
# Fabrique la version précompilée du plugin pour Raspberry Pi (ARM 64 bits),
# sur un PC Linux x86 (Ubuntu 24.04 ou Debian), en quelques minutes.
#   sudo apt install g++-aarch64-linux-gnu cmake
#   ./tete-nam/precompile/construire.sh
# Le résultat marche sur Raspberry Pi OS Bookworm et Trixie (glibc >= 2.36).
set -euo pipefail
ICI=$(cd "$(dirname "$0")" && pwd)
DEPOT=$(cd "$ICI/../.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git -C "$DEPOT" submodule update --init --recursive
aarch64-linux-gnu-gcc -O2 -fPIC -std=gnu17 -c "$ICI/compat-glibc.c" -o "$TMP/compat.o"
cat > "$TMP/arm64.cmake" <<T
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
# libstdc++ embarquée : pas de dépendance à la version de GCC du Pi
set(CMAKE_SHARED_LINKER_FLAGS_INIT "-static-libstdc++ -static-libgcc $TMP/compat.o")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
T
cmake -S "$DEPOT" -B "$TMP/build" -DCMAKE_TOOLCHAIN_FILE="$TMP/arm64.cmake" \
      -DCMAKE_BUILD_TYPE=Release -DSMART_BYPASS_ENABLED=ON
cmake --build "$TMP/build" -j"$(nproc)"
SO="$TMP/build/neural_amp_modeler.lv2/neural_amp_modeler.so"
aarch64-linux-gnu-strip "$SO"

# Vérification : pas de symbole glibc plus récent que 2.36 (Bookworm)
MAX=$(aarch64-linux-gnu-objdump -T "$SO" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)
echo "glibc la plus récente demandée : $MAX"
[ "$(printf '%s\nGLIBC_2.36\n' "$MAX" | sort -V | tail -1)" = GLIBC_2.36 ] \
    || { echo "ERREUR : trop récent pour Bookworm"; exit 1; }

tar -C "$TMP/build" -czf "$ICI/neural_amp_modeler.lv2-aarch64.tar.gz" neural_amp_modeler.lv2
"$ICI/signature.sh" > "$ICI/signature.txt"
echo "OK : $ICI/neural_amp_modeler.lv2-aarch64.tar.gz (signature $(cat "$ICI/signature.txt"))"
