# Text Processor Plugin

Plugin-Bundle, das die drei Text-Analyse-Tools aus dem Unit-2-MCP-Server als CC-/Codex-Skills verfügbar macht.

## Skills

- **Analyze Text** — Wort-/Satz-Statistiken, Vokabular-Diversität
- **Extract Keywords** — häufigste bedeutungstragende Begriffe
- **Check Reading Level** — Flesch-Kincaid Grade Level

## Voraussetzung — der MCP-Server

Dieses Plugin **enthält keinen Server-Code**. Es referenziert den `text-processor`-MCP-Server aus Unit 2 (Lesson 2-3). Zwei Konfigurations-Pfade:

### Remote (HF Spaces — bevorzugt)

In `.mcp.json` voreingestellt: `https://McCavity2-text-processor-mcp.hf.space/gradio_api/mcp/`. Beim Verwenden mit eigenem Space die URL anpassen.

### Lokal

Wenn das Unit-2-Verzeichnis `text-processor-mcp/` lokal verfügbar ist (Hennings Setup: `huggingface-context-course/2-3-building-mcp-servers-with-python/text-processor-mcp/`), `.mcp.json` umstellen auf:

```json
{
  "mcpServers": {
    "text-processor": {
      "command": "python",
      "args": ["../../2-3-building-mcp-servers-with-python/text-processor-mcp/server.py"]
    }
  }
}
```

## Verzeichnis-Struktur

```
text-processor-plugin/
├── .claude-plugin/plugin.json   # Claude-Code-Manifest
├── .codex-plugin/plugin.json    # Codex-Manifest
├── .mcp.json                    # gemeinsame MCP-Server-Referenz
├── README.md
└── skills/
    ├── analyze-text/SKILL.md
    ├── extract-keywords/SKILL.md
    └── check-reading-level/SKILL.md
```

## Lokales Test-Setup

Eine `marketplace.json` liegt eine Ebene höher (`../marketplace.json`). Installation in Claude Code:

```text
/plugin marketplace add /absoluter/pfad/3-2-building-plugins/marketplace.json
/plugin install text-processor-plugin@local-example-plugins
```

In Codex die Plugin-Directory in `~/.codex/plugins/` kopieren und in `~/.agents/plugins/marketplace.json` eintragen (siehe Lesson 3-4 "Using Plugins").

## Lizenz

MIT — siehe Repo-Root.
