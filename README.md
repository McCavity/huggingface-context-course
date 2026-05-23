# Hugging Face Context Course — Hands-On Code

> Begleitendes Code-Repository zum [Hugging Face Context Course](https://huggingface.co/learn/context-course).

Dieses Repo enthält die praktischen Übungen und Hands-On-Beispiele aus dem Kurs. Notizen, Quizze und der inhaltliche Lernfortschritt leben separat im KI-OS-Vault (`~/git/projects/own/ki-os/04-projects/context-course/`).

## Verzeichnisstruktur

Pro Lesson ein eigener Unterordner. Naming-Schema: `<Unit-Nr>-<Position-in-Unit>-<Slug-aus-Kurstitel>`.

```
huggingface-context-course/
├── 2-3-building-mcp-servers-with-python/   # Unit 2, Position 3
├── 2-7-hands-on-build-and-deploy-mcp-server/  # (folgt)
└── ...
```

## Setup

Pro Lesson ein eigenes Python-Venv (lokal, in den `venv/`-Unterordner — nicht eingecheckt).

```bash
cd 2-3-building-mcp-servers-with-python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Kurs-Fortschritt

| Unit | Thema | Status |
|---|---|---|
| 0 | Onboarding | ✓ 2026-05-14 |
| 1 | Agent Skills | ✓ 2026-05-16 |
| 2 | Model Context Protocol | In Arbeit (Lesson-Stoff durchgearbeitet 2026-05-23, Hands-On läuft) |
| 3 | Plugins | offen |
| 4 | Subagents | offen |
| 5 | Hooks | offen |
| 6 | Bonus: Nano Harness | offen |

## Lizenz

MIT — siehe [LICENSE](LICENSE).
