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

Jeden Server entweder direkt starten:

```bash
python calculator_server.py
```

oder im MCP Inspector öffnen (empfohlen, Web-UI im Browser):

```bash
mcp dev calculator_server.py
```

## Notizen + Quiz-Antworten

Inhaltliche Notizen, Quiz-Antworten und Lerneinträge: siehe Vault unter `~/git/projects/own/ki-os/04-projects/context-course/unit2-mcp-notes.md`.
