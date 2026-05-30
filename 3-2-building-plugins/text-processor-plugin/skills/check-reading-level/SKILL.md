---
name: check-reading-level
description: Use when the user asks about reading level, text difficulty, grade level, audience appropriateness, or readability of a document. Calls the text-processor MCP server's check_reading_level tool.
---

# Check Reading Level

Use the `check_reading_level` tool from the text-processor MCP server to estimate text difficulty.

## When to Use

Use this skill when the user asks about reading level, text difficulty, grade level, audience appropriateness, or readability of a piece of writing.

## How to Use

Call `check_reading_level` with the text. The tool returns JSON with:

- `grade_level` — numeric Flesch-Kincaid grade (e.g., 8.4)
- `reading_level` — categorical label (Elementary School, Middle School, High School, or College/Academic)

## Example

User: "Is this documentation appropriate for beginners?"

1. Call `check_reading_level` with the text.
2. Compare the grade level to the target audience (e.g., "general consumer docs" target Grade 8–10).
3. If the level is too high, suggest concrete simplifications — shorter sentences, simpler verbs, less nominalization. Don't just report the number; recommend an action.
