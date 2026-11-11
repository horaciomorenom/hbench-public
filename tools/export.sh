#!/bin/bash
# Make a shareable copy of hbench: everything except your machine's config, your models, your private cases
# and all results. Usage: tools/export.sh <new or empty folder, or a folder this script exported to before>
# Then: cd <folder> && git init && git add -A && git commit -m "hbench" (and push it where you like).
# Exporting again into the same folder updates it in place (files removed here are removed there; .git is kept),
# so updating the shared repo is: tools/export.sh <folder> && cd <folder> && git add -A && git commit && git push.
# The copy is checked for leftovers of your setup (LEAKS below; add your own words with EXTRA_LEAKS="a|b");
# the export fails if any are found, and the folder is left for you to inspect.
set -euo pipefail
H=$(cd "$(dirname "$0")/.." && pwd)
dest=${1:?usage: tools/export.sh <folder>}
if [ -e "$dest" ] && [ -n "$(ls -A "$dest" 2>/dev/null)" ] && [ ! -e "$dest/.hbench-export" ]; then
  echo "$dest is not empty and is not an earlier export"; exit 1
fi
mkdir -p "$dest"
rsync -a --delete --exclude '/.git/' --exclude '/.hbench-export' \
  --exclude '/runs/' --exclude '/web/jobs/' --exclude '/web/app.log' --exclude '/.venv/' \
  --exclude '/config.json' --exclude '/models.json' --exclude '/pi-agent/models.json' --exclude '/pi-agent/auth.json' \
  --exclude '/.env' --exclude '/dsh-agent/' \
  --exclude '/suites/cases.local.json' --exclude '/NOTES.local.md' --exclude '/suites/hard/' --exclude '/suites/long/' \
  --exclude '/pi-agent/models-store.json' --exclude '*.new' \
  --exclude '__pycache__/' --exclude '.DS_Store' --exclude '*.bak*' --exclude '/.git' \
  "$H/" "$dest/"
cp "$H/tools/public/suites-README.md" "$dest/suites/README.md"
echo "Exported by tools/export.sh; exporting again into this folder updates it." > "$dest/.hbench-export"
cat > "$dest/.gitignore" <<'EOF'
# Your machine and your results stay local
config.json
models.json
pi-agent/models.json
pi-agent/auth.json
pi-agent/models-store.json
.env
dsh-agent/
suites/cases.local.json
runs/
web/jobs/
web/app.log
.venv/
__pycache__/
.DS_Store
EOF
LEAKS="${HOME}|~/models|~/miniconda|/Users/|potential_field_solver|pfs-bench|DigUp|Krasny|guard_run|Qwen3\.8|hb_stage2${EXTRA_LEAKS:+|$EXTRA_LEAKS}"
hits=$(grep -rIlE "$LEAKS" "$dest" --exclude=export.sh || true)
if [ -n "$hits" ]; then
  echo "export stopped: these files mention your setup (pattern: $LEAKS):"
  grep -rInE "$LEAKS" $hits | cut -c1-160
  exit 1
fi
echo "exported to $dest ($(find "$dest" -type f | wc -l | tr -d ' ') files, $(du -sh "$dest" | cut -f1)); leak check clean"
