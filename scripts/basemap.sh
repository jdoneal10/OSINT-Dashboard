#!/usr/bin/env bash
# One-time: extract a local Protomaps basemap for the Phase 1 AOI, plus fonts and sprites,
# so the map makes no third-party requests at runtime (CLAUDE.md "Do not": outbound calls).
#
# Output (gitignored):
#   data/basemap/aoi.pmtiles           vector tiles, OpenStreetMap data (ODbL)
#   data/basemap/fonts/<stack>/*.pbf   glyphs (SIL OFL), from protomaps/basemaps-assets
#   data/basemap/sprites/v4/*          sprite sheets
#
# Env overrides: MAXZOOM (default 13), BUILD (default: latest, e.g. 20261111.pmtiles).
set -euo pipefail

cd "$(dirname "$0")/.."
OUT=data/basemap
MAXZOOM="${MAXZOOM:-13}"
mkdir -p "$OUT"

command -v pmtiles >/dev/null || { echo "pmtiles CLI not found: brew install pmtiles" >&2; exit 1; }

if [[ -z "${BUILD:-}" ]]; then
  BUILD=$(curl -fsS --max-time 30 https://build-metadata.protomaps.dev/builds.json \
    | python3 -c "import json,sys; print(sorted(b['key'] for b in json.load(sys.stdin))[-1])")
fi

# Bounding box of the Phase 1 AOI plus a 0.5° buffer, computed from the committed GeoJSON.
BBOX=$(uv run --project backend python - <<'PY'
import json
from shapely.geometry import shape
from shapely.ops import unary_union
features = json.load(open("data/reference/aoi_phase1.geojson"))["features"]
b = unary_union([shape(f["geometry"]) for f in features]).bounds
print(",".join(f"{v:.2f}" for v in (b[0] - 0.5, b[1] - 0.5, b[2] + 0.5, b[3] + 0.5)))
PY
)

echo "Extracting Protomaps build ${BUILD}, bbox ${BBOX}, maxzoom ${MAXZOOM} -> ${OUT}/aoi.pmtiles"
pmtiles extract "https://build.protomaps.com/${BUILD}" "${OUT}/aoi.pmtiles.part" \
  --bbox="${BBOX}" --maxzoom="${MAXZOOM}"
mv "${OUT}/aoi.pmtiles.part" "${OUT}/aoi.pmtiles"

echo "Fetching fonts and sprites from protomaps/basemaps-assets"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL --max-time 300 -o "$TMP/assets.tar.gz" \
  https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.tar.gz
tar -xzf "$TMP/assets.tar.gz" -C "$TMP"
rm -rf "${OUT}/fonts" "${OUT}/sprites"
cp -R "$TMP"/basemaps-assets-main/fonts "${OUT}/fonts"
cp -R "$TMP"/basemaps-assets-main/sprites "${OUT}/sprites"

cat > "${OUT}/BUILD_INFO.txt" <<EOF
protomaps_build=${BUILD}
bbox=${BBOX}
maxzoom=${MAXZOOM}
extracted=$(date -u +%Y-%m-%dT%H:%M:%SZ)
attribution=© OpenStreetMap contributors (ODbL); Protomaps
EOF

du -sh "${OUT}/aoi.pmtiles" "${OUT}/fonts" "${OUT}/sprites"
echo "Basemap ready."
