#!/usr/bin/env python3
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from openai import OpenAI

# Configuration
TASK = os.getenv("NANO_TASK", "Search for bert models on Hugging Face and summarize top 3.")
MODEL = os.getenv("NANO_MODEL", "zai-org/GLM-5.1")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://router.huggingface.co/v1")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("OPENAI_API_KEY", "")
WORKSPACE = str(Path.cwd())
MAX_STEPS = 50
TIMEOUT_S = 30
MAX_CHARS = 8000
ALLOW_WRITE = False
ALLOW_COMMANDS = ["ls", "cat", "pwd", "echo", "head", "tail", "wc", "rg", "git"]
TEMPERATURE = 0.2

SYSTEM_PROMPT = f"""You are a code-first agent.
Reply with executable Python only.

Tools:
  - list_dir(path='.') → list files
  - read_file(path, max_chars=4000) → read file
  - write_file(path, content) → write file (only if ALLOW_WRITE=True)
  - exec_cmd(args) → run allowed command
  - web_fetch(url, max_bytes=10000) → fetch webpage
  - hf_search(query, limit=5) → search HF Hub (id, author, downloads, likes, pipeline_tag, library_name, tags)
  - git_log(limit=10) → recent git commits (oneline)

Allowed commands: {ALLOW_COMMANDS}
Writes enabled: {ALLOW_WRITE}

When done, call final_answer(result).
Output only Python code, no prose."""

def clip(x, n=MAX_CHARS):
    s = str(x)
    return s[:n] + f"\n...[truncated]" if len(s) > n else s

def main():
    ws = Path(WORKSPACE).resolve()
    done = False
    final_result = None

    def safe_path(path):
        p = (ws / path).resolve()
        try:
            p.relative_to(ws)
        except ValueError:
            raise ValueError(f"Path escapes workspace: {path}")
        return p

    def list_dir(path="."):
        p = safe_path(path)
        return sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())

    def read_file(path, max_chars=4000):
        p = safe_path(path)
        return clip(p.read_text(errors="replace"), min(max_chars, MAX_CHARS))

    def write_file(path, content):
        if not ALLOW_WRITE:
            raise PermissionError("write_file disabled")
        p = safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(content), encoding="utf-8")
        return f"Wrote {len(str(content))} bytes"

    def exec_cmd(args):
        if args[0] not in ALLOW_COMMANDS:
            raise PermissionError(f"Command {args[0]} not allowed")
        result = subprocess.run(
            args, capture_output=True, timeout=TIMEOUT_S, text=True
        )
        output_parts = []
        if result.stdout:
            output_parts.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"stderr:\n{result.stderr}")
        output = "\n\n".join(output_parts) or f"(exit code {result.returncode} with no output)"
        return clip(output, MAX_CHARS)

    def web_fetch(url, max_bytes=10000):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
                content = r.read(max_bytes)
                return content.decode("utf-8", errors="replace")
        except Exception as e:
            return f"Error: {type(e).__name__}: {str(e)}"

    def hf_search(query, resource_type="models", limit=5):
        if not API_KEY:
            return "Error: HF_TOKEN not set"
        try:
            url = f"https://huggingface.co/api/{resource_type}"
            req = urllib.request.Request(
                f"{url}?search={query}&limit={limit}",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = json.loads(r.read())
                results = []
                for item in data[:limit]:
                    mid = item.get("id", "") or ""
                    results.append({
                        "id": mid,
                        "author": item.get("author") or (mid.split("/")[0] if "/" in mid else "N/A"),
                        "downloads": item.get("downloads", 0),
                        "likes": item.get("likes", 0),
                        "pipeline_tag": item.get("pipeline_tag", "N/A"),
                        "library_name": item.get("library_name", "N/A"),
                        "tags": (item.get("tags") or [])[:8],
                    })
                return results
        except Exception as e:
            return f"Error: {str(e)}"

    def git_log(limit=10):
        """Recent git commits (oneline)."""
        return exec_cmd(["git", "log", "--oneline", f"-{limit}"])

    def final_answer(value):
        nonlocal done, final_result
        done = True
        final_result = value
        return value

    # Initialize
    client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": TASK}
    ]

    # Main loop
    for step in range(MAX_STEPS):
        print(f"\n[Step {step + 1}]")

        # Call LLM
        response = client.responses.create(
            model=MODEL,
            temperature=TEMPERATURE,
            input=messages
        )

        content = response.output_text
        print(f"Model:\n{content[:300]}...")

        messages.append({"role": "assistant", "content": content})

        # Execute code
        try:
            code_match = re.search(r"```python\n(.*?)\n```", content, re.DOTALL)
            if not code_match:
                raise ValueError("No Python code block found")

            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()

            exec_globals = {
                "__builtins__": {},
                "list_dir": list_dir,
                "read_file": read_file,
                "write_file": write_file,
                "exec_cmd": exec_cmd,
                "web_fetch": web_fetch,
                "hf_search": hf_search,
                "git_log": git_log,
                "final_answer": final_answer,
                "json": json
            }

            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exec(code_match.group(1), exec_globals)

            stdout_text = stdout_buffer.getvalue().strip()
            stderr_text = stderr_buffer.getvalue().strip()

            if done:
                result = f"Final answer: {clip(final_result)}"
            else:
                observations = []
                if stdout_text:
                    observations.append(f"stdout:\n{clip(stdout_text)}")
                if stderr_text:
                    observations.append(f"stderr:\n{clip(stderr_text)}")
                result = "\n\n".join(observations) or "Executed successfully (no output)"
        except FileNotFoundError:
            result = "Error: FileNotFoundError: File not found"
        except PermissionError as e:
            result = f"Error: PermissionError: {str(e)}"
        except subprocess.TimeoutExpired:
            result = "Error: TimeoutError: Command took too long"
        except Exception as e:
            result = f"Error: {type(e).__name__}: {str(e)}"

        if done:
            print(f"✓ Task complete: {final_result}")
            break

        messages.append({"role": "user", "content": result})

    if not done:
        print(f"✗ Max steps reached")

if __name__ == "__main__":
    main()
