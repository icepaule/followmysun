#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCAD="$HERE/olimex_esp32_evb_ea_roof_housing_v0.3.scad"
OUT="$HERE/dist"
OPENSCAD="${OPENSCAD:-openscad}"

mkdir -p "$OUT"

render() {
  local part="$1"
  local outfile="$2"
  echo "[OpenSCAD] $part -> $outfile"
  "$OPENSCAD" -o "$OUT/$outfile" -D "part=\"$part\"" "$SCAD"
}

render base       base_v0.3.stl
render lid        lid_v0.3.stl
render rst_button rst_button_v0.3.stl
render fit_test   fit_test_v0.3.stl

cp "$SCAD" "$OUT/"
cp "$HERE/README.md" "$OUT/"
cp "$HERE/SOURCE_POSITIONS.md" "$OUT/"
cp "$HERE/MESH_QA.json" "$OUT/"

(
  cd "$OUT"
  sha256sum *.stl *.scad README.md SOURCE_POSITIONS.md MESH_QA.json > MANIFEST_SHA256.txt
  rm -f olimex_esp32_evb_ea_roof_housing_v0.3.zip
  zip -9 olimex_esp32_evb_ea_roof_housing_v0.3.zip \
    base_v0.3.stl lid_v0.3.stl rst_button_v0.3.stl fit_test_v0.3.stl \
    olimex_esp32_evb_ea_roof_housing_v0.3.scad README.md \
    SOURCE_POSITIONS.md MESH_QA.json MANIFEST_SHA256.txt
)

echo
echo "Fertig: $OUT"
ls -lh "$OUT"/*.stl "$OUT"/*.zip
