# Contributing

Thanks for helping improve Standup → Jira Auto-Notes.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill secrets locally — never commit .env
chmod 600 .env
```

Always verify with a dry-run:

```bash
python main.py --file samples/sample_transcript.txt
```

Do **not** run `--live` against shared/production Jira unless you intend to post.

## Before opening a PR

1. Run `./scripts/oss_check.sh` (fails if secrets or local artifacts would be published).
2. Keep changes focused; match existing module boundaries (`config`, `pipeline`, `llm`, …).
3. Do not weaken allowlisting, dry-run defaults, or HTTPS validation without a strong reason.
4. Do not commit `.env`, service-account JSON, logs, `.state/`, or promo folders.
5. If you change LLM behavior, update `.cursor/skills/standup-jira-automation/prompts.md` too when prompts change.

## Reporting bugs

Use GitHub Issues for functional bugs and feature requests. For security issues, see [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the MIT License.
