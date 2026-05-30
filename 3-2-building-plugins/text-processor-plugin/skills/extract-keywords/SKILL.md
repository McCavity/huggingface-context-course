---
name: extract-keywords
description: Use when the user asks for keywords, key terms, topic extraction, tags, or quick content summarization of a piece of text. Calls the text-processor MCP server's extract_keywords tool.
---

# Extract Keywords

Use the `extract_keywords` tool from the text-processor MCP server to find the most important words in text.

## When to Use

Use this skill when the user asks for keywords, key terms, topic extraction, tagging suggestions, or quick content summarization.

## How to Use

Call `extract_keywords` with the text and an optional `count` parameter (default: 5). The tool returns JSON with a `keywords` array — each entry contains `word` and `frequency`.

For multi-topic documents, prefer `count=10` so themes can be grouped. For short paragraphs, the default of 5 is enough.

## Example

User: "What are the main topics in this article?"

1. Call `extract_keywords` with `count=10`.
2. Group semantically related keywords into themes (e.g., "vehicle, engine, fuel, mileage" → "automotive").
3. Present 2–3 themes with their supporting keyword frequencies. Do not just list the raw keyword array — interpret it.
