# Unit 6 — Nano Harness (Extending)

Hands-on for [Context Course Unit 6 — Nano Harness](https://huggingface.co/learn/context-course/unit6/introduction):
the ~220-line code-first agent, extended with two tools and run against `zai-org/GLM-5.1`
via Hugging Face Inference Providers.

## What's here

- `nano_harness_extended.py` — the full harness (6 base tools) plus two own extensions:
  - **enriched `hf_search`** — returns `id`, `author`, `downloads`, `likes`, `pipeline_tag`, `library_name`, `tags`
  - **`git_log`** — recent commits (`"git"` added to the command allowlist)
  - `TASK` is overridable via the `NANO_TASK` env var (so different tasks run without editing the file)

## Run

```bash
python3 -m venv .venv && ./.venv/bin/pip install openai
# token needs the "Make calls to Inference Providers" permission:
printf 'HF_TOKEN=%s\n' 'hf_your_token' > .env
export HF_TOKEN="$(sed -n 's/^HF_TOKEN=//p' .env | head -1 | tr -d '[:space:]')"
./.venv/bin/python nano_harness_extended.py
# different task:
NANO_TASK="Use git_log to summarize the 5 most recent commits." ./.venv/bin/python nano_harness_extended.py
```

`.venv/` and `.env` are gitignored. The token is loaded by text-extraction — the `.env` is **never executed as a shell file** (a bare-token line once leaked a token through a shell error message; this avoids that).

## Key takeaways

- **Code-first (CodeAct):** the model emits Python that calls tools; the harness `exec()`s it with `__builtins__` stripped and only the tools exposed — security at the language level *and* the tool boundary (`safe_path` path-confinement, command allowlist, write-off-by-default).
- **Errors become observations**, so the loop self-corrects. GLM-5.1 needed several steps to learn the `final_answer()` protocol — protocol adherence is model-dependent.
- **`MAX_STEPS` guarantees termination.** The same loop runs unchanged against any Inference-Providers model — swap `NANO_MODEL` / `OPENAI_BASE_URL` (the hook for pointing it at a self-built model later).
