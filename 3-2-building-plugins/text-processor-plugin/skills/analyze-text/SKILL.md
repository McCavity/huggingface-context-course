---
name: analyze-text
description: Use when the user asks about text statistics — word counts, character counts, sentence counts, vocabulary diversity, or readability metrics. Calls the text-processor MCP server's analyze_text tool and explains the result in plain language.
---

# Analyze Text

Use the `analyze_text` tool from the text-processor MCP server to compute text statistics.

## When to Use

Use this skill when the user asks about text statistics, word counts, character counts, sentence counts, average word length, or readability metrics. Also when the user wants a quick complexity sanity check on a paragraph or document.

## How to Use

Call the `analyze_text` tool with the full text as input. The tool returns JSON with:

- `total_characters`, `characters_without_spaces`
- `total_words`, `total_sentences`
- `average_word_length`, `average_sentence_length`
- `unique_words`

Interpret the numbers in context. A high `unique_words` / `total_words` ratio signals diverse vocabulary; long `average_sentence_length` signals complex prose; very short averages signal terse or list-like text.

## Example

User: "How complex is this paragraph?"

1. Call `analyze_text` with the paragraph.
2. Compare the statistics against typical baselines (e.g., 15–20 words/sentence is conversational, 25+ is academic).
3. Summarize findings in plain language — focus on the one or two metrics that stand out, not all eight.
