# Model routing

`agent/router.py` sorts each request into a route using fast local keyword rules. The route decides which Claude model the main agent uses. The switch happens per request, with `client.set_model()`.

| Route | Triggers (examples) | Model setting |
|---|---|---|
| simple | short commands | `model_fast` (sonnet) |
| computer | open, type, press, file, folder | `model_fast` |
| vision | screen, look at, click, fill this | `model_reasoning` (opus) |
| research | research, compare, analyze, is it worth | `model_reasoning` |
| writing | write, draft, reply, summarize | `model_reasoning` |
| reasoning | plan, prepare, why, contract, organize, long requests | `model_reasoning` |

You can change the models in `data/settings.json` or by voice ("change setting model_fast to opus").

## Providers (`agent/providers.py`)
`ModelProvider.complete(prompt, system, model) -> (text, exact_label)`

- **ClaudeProvider:** a one-shot Claude call through the Agent SDK with no tools. It gives an independent opinion and is always available.
- **OpenAIProvider:** only available when `OPENAI_API_KEY` is set and `pip install openai` has been run.
- **MockProvider:** for tests.

`consult_model` runs the requested providers in parallel and records each call as a `consult` trace entry with its latency. Results are labelled with the model that actually answered. A provider that isn't configured is reported as **not consulted**, and the tests check this.

## Cost and context
- Simple requests go to the fast model.
- The Claude Agent SDK compacts long sessions automatically.
- Saying "new conversation" resets the session.
- Context injection is capped at 6 memories and 6 due items.
- Budgets: `max_turns=40` per request. The SDK also supports `max_budget_usd`, which isn't used because this runs on a subscription.
