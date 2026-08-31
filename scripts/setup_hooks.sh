#!/usr/bin/env bash
# Install the AI-log pre-push hook.
set -e

HOOK_FILE=".git/hooks/pre-push"

cat > "$HOOK_FILE" <<'EOF'
#!/usr/bin/env bash
# Collect and submit AI logs without blocking pushes.
bash scripts/_pyrun.sh scripts/log_claude.py --auto || true
bash scripts/_pyrun.sh scripts/log_codex.py --auto || true
bash scripts/_pyrun.sh scripts/log_antigravity.py --auto || true
bash scripts/_pyrun.sh scripts/submit_log.py || true
exit 0
EOF

chmod +x "$HOOK_FILE"
chmod +x scripts/_pyrun.sh 2>/dev/null || true
echo "[ai-log] Git pre-push hook installed."

mkdir -p .ai-log
touch .ai-log/.gitkeep

echo "[ai-log] Setup complete. Configure AI_LOG_SERVER in your .env file."
