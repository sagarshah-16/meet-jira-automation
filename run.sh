#!/bin/zsh
# One-shot standup sync: find latest transcript -> post notes to Jira.
# Used by the Desktop button (Run Standup Sync.command) and cron/launchd later.
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p logs
LOG="logs/run-$(date +%Y%m%d-%H%M%S).log"

echo "▶ Standup → Jira sync starting ($(date))" | tee "$LOG"
if .venv/bin/python main.py --live 2>&1 | tee -a "$LOG"; then
  SUMMARY=$(grep -E "Run complete|already processed|No new transcript" "$LOG" | tail -1 || true)
  osascript -e "display notification \"${SUMMARY:-Done}\" with title \"Standup → Jira\" sound name \"Glass\"" || true
else
  osascript -e 'display notification "Run FAILED — see Terminal/logs" with title "Standup → Jira" sound name "Basso"' || true
  exit 1
fi
