#!/usr/bin/env bash
# Pre-publish hygiene: fail if secrets or local-only artifacts are staged/tracked.
set -euo pipefail
cd "$(dirname "$0")/.."

RED=$'\033[31m'
GRN=$'\033[32m'
RST=$'\033[0m'
fail=0

say_fail() { echo "${RED}✗${RST} $1"; fail=1; }
say_ok() { echo "${GRN}✓${RST} $1"; }

if [[ ! -d .git ]]; then
  echo "No .git directory yet — run: git init"
fi

# Block obvious secret filenames if present and not ignored
for f in .env service-account.json credentials.json; do
  if [[ -e "$f" ]]; then
    if [[ -d .git ]] && git check-ignore -q "$f"; then
      say_ok "$f exists locally and is gitignored"
    elif [[ ! -d .git ]]; then
      say_ok "$f exists locally (gitignore will apply after git init)"
    else
      say_fail "$f is present and NOT ignored — do not publish"
    fi
  fi
done

# Scan publishable text for high-risk patterns (exclude this script)
if command -v rg >/dev/null 2>&1; then
  matches="$(
    rg -n --hidden \
      -g '!.git/**' -g '!.venv/**' -g '!linkedin-*/**' -g '!scripts/oss_check.sh' \
      -e 'sk-[A-Za-z0-9]{20,}' \
      -e '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----' \
      -e '"private_key":\s*"' \
      README.md LICENSE SECURITY.md CONTRIBUTING.md main.py requirements.txt \
      .env.example standup_notes samples .cursor/skills 2>/dev/null || true
  )"
  if [[ -n "$matches" ]]; then
    echo "$matches"
    say_fail "Possible secret material matched in publishable paths"
  else
    say_ok "No high-risk secret patterns in publishable paths"
  fi
else
  echo "rg not found — skipped content secret scan"
fi

if [[ -f samples/sample_transcript_ad.txt ]]; then
  say_fail "samples/sample_transcript_ad.txt looks org-specific — remove before publish"
else
  say_ok "No org-specific AD sample transcript"
fi

promo_ok=1
for d in linkedin-video linkedin-hyperframes; do
  if [[ -d "$d" ]]; then
    if [[ -d .git ]] && git check-ignore -q "$d"; then
      :
    elif [[ ! -d .git ]]; then
      :
    else
      say_fail "$d is not gitignored — exclude before publish"
      promo_ok=0
    fi
  fi
done
if [[ "$promo_ok" -eq 1 ]]; then
  if [[ -d linkedin-video || -d linkedin-hyperframes ]]; then
    say_ok "Promo folders present locally but gitignored"
  else
    say_ok "No local promo folders"
  fi
fi

# Ensure .env.example has no real-looking tokens
if [[ -f .env.example ]] && rg -q 'sk-[A-Za-z0-9]{20,}' .env.example 2>/dev/null; then
  say_fail ".env.example appears to contain a real OpenAI key"
else
  say_ok ".env.example looks like a template"
fi

if [[ "$fail" -ne 0 ]]; then
  echo
  echo "oss_check failed — fix the items above before open-sourcing."
  exit 1
fi

echo
echo "oss_check passed."
