#!/usr/bin/env bash
# Check that the image holds no site data and no secrets, even with decoys in
# the build context: `.dockerignore` must keep them out. Needs only Docker.
set -euo pipefail

decoys=(wes/.env wes/.env.local wes/decoy.key tests/kits/decoy.pem)
cleanup() {
    rm -f "${decoys[@]}"
    rmdir tests/kits 2>/dev/null || true
    docker image rm -f nvflare-testbed:contents >/dev/null 2>&1 || true
}
trap cleanup EXIT

mkdir -p tests/kits
for decoy in "${decoys[@]}"; do
    echo "decoy" >"${decoy}"
done
docker build -q -f images/Dockerfile.flare -t nvflare-testbed:contents . >/dev/null

found="$(docker run --rm --network none --entrypoint find nvflare-testbed:contents /app /usr/local/bin \
    \( -name '*.csv' -o -name '.env*' -o -name '*.key' -o -name '*.pem' -o -name 'kits' -o -name 'decoy*' \) -print)"
if [ -n "${found}" ]; then
    echo "[FAIL] found in the image:"
    echo "${found}"
    exit 1
fi
echo "[ok] no site data or secrets in the image"
