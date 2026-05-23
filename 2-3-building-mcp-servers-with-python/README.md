# Building MCP Servers with Python

> Unit 2 · Position 3 · [Kursseite](https://huggingface.co/learn/context-course/unit2/building-servers)

## Ziel der Lesson

Mit FastMCP einen eigenen MCP-Server bauen — von einem Calculator-Minimal-Server bis zu Tools mit File-I/O, Resources und Prompts.

## Inhalt dieses Verzeichnisses

Hier landen die Code-Übungen aus der Kursseite, in der Reihenfolge der Lesson:

1. `calculator_server.py` — Minimal-Server (2 Tools: add, multiply)
2. `file_analyzer.py` — Komplexere Tools (read_file, count_lines, list_directory)
3. `documentation_server.py` — Tools + Resources
4. `prompts_server.py` — Tools + Prompts
5. `safe_operations.py` — Fehlerbehandlung

(Dateinamen können je nach Iteration abweichen — Quelle ist der Lesson-Text.)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Testen

### Variante A: MCP Inspector (empfohlen, komfortabel)

```bash
mcp dev calculator_server.py
```

Öffnet ein Web-UI im Browser, das die Tools auflistet und einen GUI-Aufruf erlaubt. Initialisierungs-Handshake macht der Inspector unsichtbar im Hintergrund.

### Variante B: Direkt via stdin/stdout (lehrreich, weil man sieht was passiert)

Die Kursseite sagt nur "starte den Server". Was sie verschweigt: nach `python calculator_server.py` sitzt man vor einem schwarzen Terminal, der Server wartet stumm auf JSON-RPC-Messages über stdin. **Erstmal überhaupt nichts zu sehen ist hier richtig**, nicht falsch. Man muss selbst eine JSON-RPC-Message tippen.

**Wichtig:** Jede Message ist eine **einzelne Zeile** JSON (Newline = Message-Trenner). Multiline-JSON funktioniert nicht.

#### Initialisierungs-Handshake (sonst geht gar nichts)

MCP verlangt **vor** der ersten echten Anfrage einen zweistufigen Handshake — anders als HTTP, wo die Initialisierung mit dem Verbindungsaufbau abgeschlossen ist. Beim direkten stdin/stdout-Test muss man den Handshake **selbst** machen:

**Schritt 1 — `initialize` senden (Request, erwartet Antwort):**

```json
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual-test","version":"0.0.1"}}}
```

Antwort des Servers (gekürzt):

```json
{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2024-11-05","capabilities":{...},"serverInfo":{"name":"calculator","version":"1.27.1"}}}
```

**Schritt 2 — `notifications/initialized` senden (kein `id`, ist eine Notification, keine Anfrage):**

```json
{"jsonrpc":"2.0","method":"notifications/initialized"}
```

Diese Notification löst **keine Antwort** aus — kein Echo, kein OK, nichts. Das ist korrektes Verhalten, nicht ein Fehler. Ab jetzt ist die Session "live".

> **Beobachtung beim ersten eigenen Lauf:** FastMCP scheint tolerant zu sein und akzeptierte `tools/list`/`tools/call` auch nach **nur** Schritt 2 (Schritt 1 weggelassen). Das ist **kein Spec-konformes Verhalten** und sollte sich nicht reproduzieren lassen mit strikteren MCP-Server-Implementierungen oder zukünftigen FastMCP-Versionen. Production-Clients senden immer beide Schritte. Beim manuellen Testen: gewöhne dir den vollen Handshake an, sonst sitzt du irgendwann auf einer halb initialisierten Session und wunderst dich.

#### Tools entdecken

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

Antwort: Liste aller registrierten Tools mit `inputSchema` und `outputSchema` (FastMCP generiert die Schemas automatisch aus Type-Hints + Docstrings).

#### Tool aufrufen

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"add","arguments":{"a":20,"b":22}}}
```

Antwort:

```json
{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"42"}],"structuredContent":{"result":42},"isError":false}}
```

> **Type-Coercion-Stolperfalle:** Das Schema deklariert `integer`, aber FastMCP (via Pydantic) ist tolerant und akzeptiert auch String-Werte: `{"a": "20", "b": "22"}` liefert ebenfalls `42`. Das ist Pydantics impliziter Konverter (`int("20") == 20`). **Verlass dich nicht drauf** — andere MCP-Server (z.B. mit strikt typed Validatoren) werden Strings zurückweisen, und für nicht-konvertierbare Werte (`"a": "zwanzig"`) crasht es ohnehin. Sende Zahlen als Zahlen.

#### Typischer Fehler ohne Handshake

```
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
WARNING  Failed to validate request: Received request before initialization was complete
{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Invalid request parameters","data":""}}
```

→ Das ist das Symptom für "Initialisierung fehlt". Lösung: erst `initialize`, dann `notifications/initialized`, **dann** richtige Anfragen.

**Quellen-Hinweis:** Den Handshake-Schritt findet man in der Kurssseite nicht — aber zum Beispiel auf StackOverflow: [MCP server always get initialization error](https://stackoverflow.com/questions/79550897/mcp-server-always-get-initialization-error).

## Notizen + Quiz-Antworten

Inhaltliche Notizen, Quiz-Antworten und Lerneinträge: siehe Vault unter `~/git/projects/own/ki-os/04-projects/context-course/unit2-mcp-notes.md`.
