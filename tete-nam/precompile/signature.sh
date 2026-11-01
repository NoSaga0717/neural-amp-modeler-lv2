#!/bin/bash
# Empreinte des sources du plugin (code, moteur NeuralAudio, options).
# Si elle change, la version précompilée n'est plus à jour.
DEPOT=$(cd "$(dirname "$0")/../.." && pwd)
OPTIONS="-DCMAKE_BUILD_TYPE=Release -DSMART_BYPASS_ENABLED=ON"
for chemin in CMakeLists.txt src resources deps/NeuralAudio deps/lv2; do
    git -C "$DEPOT" rev-parse "HEAD:$chemin"
done | { cat; echo "$OPTIONS"; } | sha256sum | cut -c1-16
