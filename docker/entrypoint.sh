#!/usr/bin/env bash
# Container start-up: put the writable directories where they belong, fetch the model,
# migrate, and hand over to gunicorn.
set -euo pipefail

DATA_DIR="${SOULFONT_DATA_DIR:-/app}"
mkdir -p "$DATA_DIR/media" "$DATA_DIR/workdir" "$DATA_DIR/checkpoints"

# MEDIA_ROOT points at the data directory, so the placeholder font every UserData row
# defaults to has to be copied across the first time. Without it the gallery renders
# rows whose font file does not exist.
if [ ! -f "$DATA_DIR/media/ttf_files/MaruBuri-Regular.ttf" ] && [ -d /app/media ]; then
  echo "[boot] seeding bundled media"
  cp -R /app/media/. "$DATA_DIR/media/"
fi

# The pipeline resolves both of these relative to the project root, so they are linked
# rather than configured. workdir/ is disposable by design; checkpoints/ is linked so a
# persistent volume keeps the 183MB download across restarts.
ln -sfn "$DATA_DIR/workdir" /app/workdir
ln -sfn "$DATA_DIR/checkpoints" /app/checkpoints

CKPT="$DATA_DIR/checkpoints/korean-handwriting.pth"
if [ ! -f "$CKPT" ]; then
  if [ -n "${SOULFONT_CHECKPOINT_URL:-}" ]; then
    echo "[boot] downloading checkpoint (183MB)"
    # A private Hugging Face repo needs the token; a public URL ignores the header.
    if [ -n "${HF_TOKEN:-}" ]; then
      curl -fsSL -H "Authorization: Bearer ${HF_TOKEN}" "${SOULFONT_CHECKPOINT_URL}" -o "$CKPT.part"
    else
      curl -fsSL "${SOULFONT_CHECKPOINT_URL}" -o "$CKPT.part"
    fi
    mv "$CKPT.part" "$CKPT"
  else
    # Not fatal: every page except font generation works without it, and failing to
    # boot would leave no way to see the error.
    echo "[boot] WARNING: no checkpoint and SOULFONT_CHECKPOINT_URL is unset."
    echo "[boot] The site will run but font generation will fail at inference."
  fi
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput --clear

# One worker, several threads. Each worker process would load its own copy of the model
# (183MB of weights plus torch's own footprint), and generation runs as a background
# thread inside the worker that started it — a second worker cannot see or finish it.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-7860}" \
  --workers 1 \
  --threads 8 \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
