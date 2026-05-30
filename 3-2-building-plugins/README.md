# 3-2 Building Plugins — Hands-On

Begleitcode zur Lesson [Building Your Own Plugin](https://huggingface.co/learn/context-course/unit3/building-plugins) (Unit 3, Position 2).

## Lernziel der Lesson

Den Unit-2-MCP-Server (`text-processor`) als **Plugin** verpacken — ohne neuen Server-Code. Skills beschreiben *wann* die MCP-Tools zu nutzen sind, `.mcp.json` referenziert den bestehenden Server.

## Inhalt dieses Verzeichnisses

| Datei/Dir | Zweck |
|---|---|
| `text-processor-plugin/.claude-plugin/plugin.json` | Claude-Code-Manifest |
| `text-processor-plugin/.codex-plugin/plugin.json` | Codex-Manifest mit `interface.displayName` |
| `text-processor-plugin/.mcp.json` | gemeinsame MCP-Server-Referenz auf Hennings HF Space |
| `text-processor-plugin/skills/analyze-text/SKILL.md` | Skill für Text-Statistik |
| `text-processor-plugin/skills/extract-keywords/SKILL.md` | Skill für Keyword-Extraktion |
| `text-processor-plugin/skills/check-reading-level/SKILL.md` | Skill für Grade Level |
| `text-processor-plugin/README.md` | Plugin-eigene Doku |
| `marketplace.json` | lokale Marketplace-Datei für CC-Tests |

## Walkthrough-Lücken — was der Kurs übergeht

Wie schon Unit 1 und Unit 2 hat auch dieser Walkthrough Sprünge, die ein erfahrener Lerner abfedert. Für den eigenen Re-Run hier die Notizen:

### Lücke 1: „Was ist mein MCP-Endpoint?"

Die Lesson sagt „Update the URL to your deployed Space" — setzt aber voraus, dass Lerner ihren eigenen HF-Space-Namen kennen UND wissen, dass das Gradio-MCP-Pfad-Schema `gradio_api/mcp/` ist (nicht `mcp/` allein).

**Hennings Endpoint:** `https://McCavity2-text-processor-mcp.hf.space/gradio_api/mcp/`

Pfad-Aufbau: `https://<owner-lower>-<space-name-lower>.hf.space/gradio_api/mcp/`. Owner + Space-Name werden lowercased und mit Bindestrich verbunden — eine kleine Falle wenn der eigene HF-Username gemischte Case hat (bei mir `McCavity2` → `mccavity2` in der URL).

### Lücke 2: Lokal vs. Remote — welcher Pfad zuerst?

Die Lesson stellt beide Varianten parallel hin. Pragmatisch lohnt sich der **Remote-Pfad zuerst**: weniger Setup, kein Python-Pfad-Geraten, Plugin funktioniert von überall. Der lokale Pfad wird relevant wenn man am Server selbst entwickelt.

Hier voreingestellt: Remote (HF Space). Lokal-Variante in der Plugin-README dokumentiert.

### Lücke 3: Wie testet man wirklich?

Die Lesson zeigt `/plugin marketplace add /abs/path` + `/plugin install <name>@<marketplace-name>` — aber zwischen Edit und nächstem Test muss man im `/plugin`-Browser disable + re-enable. Das wird nur am Rand erwähnt, ist aber der Iterations-Loop, den man verstanden haben muss.

**Reproduzierbare Iterations-Schleife:**
1. Edit in einer SKILL.md oder `plugin.json`
2. `/plugin` öffnen
3. Plugin disable
4. Plugin enable
5. Sofort testen mit einer Beispiel-Anfrage

## Test-Anfragen

Drei Mini-Prompts zum Verifizieren, dass jedes Skill triggert + sein MCP-Tool aufruft:

**Analyze Text:**

```
How complex is the writing in this paragraph? "The mitochondria is the powerhouse
of the cell. It provides energy through oxidative phosphorylation, a process
involving the electron transport chain and ATP synthase."
```

Erwartung: `analyze-text`-Skill triggert → `analyze_text` MCP-Call → Antwort mit Word-/Sentence-Stats.

**Extract Keywords:**

```
What are the main topics in this article? "<beliebiger längerer Text>"
```

Erwartung: `extract-keywords`-Skill triggert → `extract_keywords` MCP-Call → Top-N-Keywords als Themen gruppiert.

**Check Reading Level:**

```
Is this README appropriate for beginners? "<README-Inhalt>"
```

Erwartung: `check-reading-level`-Skill triggert → `check_reading_level` MCP-Call → Grade Level + Empfehlung.

## Was im Plugin NICHT drin ist

Bewusst weggelassen vom Lesson-Walkthrough — und hier auch nicht eingebaut:

- **Keine `agents/`-Subagenten** — Lesson erwähnt sie nur als Plugin-Option, nicht in der Übung
- **Keine Hooks** — `hooks/`-Verzeichnis ist optional und nicht Teil der Lesson
- **Kein OpenCode-Branch** — nicht relevant für Hennings primären Workflow (CC + Codex); kann später nachgezogen werden, wenn das OpenCode-Setup für Unit 4 wieder genutzt wird
- **Kein Pi-Branch** — Pi parkt für Unit 6 (Nano Harness)

## Notizen, Quizze, Reflexion

Konzeptionelle Notizen + Quiz-Antworten im Vault: `~/git/projects/own/ki-os/04-projects/context-course/unit3-plugins-notes.md`.
