# Unit 4 — Sub-agents (Hands-On)

Context Course Unit 4 hands-on. The real takeaway is **`.claude/agents/`** — four custom
sub-agent definitions (implementer, researcher, security-reviewer, performance-reviewer).

`main.py` + `auth/` + `tests/` are the exercise's **output**: an OAuth pipeline the agents
were pointed at. The course prompt was a bit artificial (build an OAuth pipeline before there
is even an app), so the pipeline code is illustrative rather than a polished deliverable —
kept here for traceability of what the sub-agent workflow produced.
