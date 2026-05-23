# CLAUDE.md — huggingface-context-course

> Letzte Aktualisierung: 2026-05-23

## Was ist das?

Hands-On Code-Repo zum [Hugging Face Context Course](https://huggingface.co/learn/context-course). **Code-Übungen**, nichts anderes. Notizen, Quiz-Antworten und der inhaltliche Lern-Tracker leben im KI-OS-Vault: `~/git/projects/own/ki-os/04-projects/context-course/`.

## Verzeichnis-Konvention

Pro Lesson ein Unterordner. Schema: `<Unit-Nr>-<Position-in-Unit>-<Slug-aus-Kurstitel>`.

Beispiele:
- `2-3-building-mcp-servers-with-python/` — Unit 2, Position 3 ("Building MCP Servers with Python")
- `2-7-hands-on-build-and-deploy-mcp-server/` — Unit 2, Position 7 (das Hands-On-Projekt)

Position = Reihenfolge auf der Kurssidebar (inkl. Quizzes — Quizzes überspringen wir hier, aber der Zähler läuft mit, damit die Nummerierung mit dem Kurs übereinstimmt).

## Python-Setup pro Lesson

Jede Lesson hat ihr eigenes `venv/`-Verzeichnis. **Nicht eingecheckt** (siehe `.gitignore`). Idee: jede Lesson ist selbstständig reproduzierbar — kein Cross-Lesson-State.

```bash
cd <lesson-dir>
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Python-Version: aktuell 3.14.4 (Homebrew). System-Python (`/usr/bin/python3`, 3.9) **nicht** verwenden — PEP-668-blockiert auf macOS und alte Sprachfeatures fehlen.

## Git-Konventionen

- **Solo-Maintainer-Pattern:** PR-basiert für nicht-triviale Änderungen, direkt-auf-main für Quick-Fixes.
- Branch Protection: `required_approving_review_count: 0`, `enforce_admins: false`, no force-push, no deletion.
- Commit-Messages auf Deutsch, kurz und beschreibend.
- Code-Übungen: jede Lesson sollte als atomarer Commit landen (oder mehrere Atom-Commits, wenn Iterationen sichtbar bleiben sollen).

## Was hier NICHT hingehört

- Quiz-Antworten oder Kurs-Notizen → KI-OS-Vault
- Lerneinträge / Aha-Momente → KI-OS `CLAUDE.md` Lernprotokoll
- Open Loops / Folgeaufgaben → KI-OS `open-loops.md`
- API-Keys, Tokens, `.env`-Werte → niemals committen, immer `.gitignore` prüfen
