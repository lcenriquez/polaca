#!/usr/bin/env bash
# Copia la base y las fuentes crudas al volumen de Fly (montado en /data).
# Excluye a propósito: datos/cache (regenerable) y datos/evidencia (fotos
# ciudadanas, no se suben a la demo). Ejecutar desde la raíz del repo.
set -euo pipefail

APP="${FLY_APP:-polaca-demo}"

for f in datos/auditor.db datos/raw; do
  [ -e "$f" ] || { echo "Falta $f — corre esto desde la raíz del repo." >&2; exit 1; }
done

fly ssh sftp shell --app "$APP" <<'EOF'
mkdir /data/raw
put datos/auditor.db /data/auditor.db
put -r datos/raw /data/
EOF

echo "Listo: auditor.db y raw/ están en /data del volumen (app: $APP)."
echo "No se subió datos/cache ni datos/evidencia."
