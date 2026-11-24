# Contributing

- Every action that touches the outside world has to be a `Tool` with the correct `Risk`. Never call side effects directly from the agent.
- Add connectors as adapters (`connectors/base.py`) with a mock. Don't hard-code a provider anywhere else.
- External text must go through `wrap_untrusted`.
- Every new tool or component needs tests. Run `python -m pytest tests -q` before committing.
- Never commit `.env`, `credentials.json`, `token.json` or `data/`.
