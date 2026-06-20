# Code Quality Pipeline

## Architecture

This project uses a multi-agent workflow:
1. **Research** — Understand existing code
2. **Implement** — Write new features
3. **Verify** — Security and performance review

## Workflow Triggers

### Before Implementation
When the user asks for a new feature:
1. Use the researcher subagent first
2. Have it explore the codebase (15+ files)
3. Document architecture and relevant patterns
4. Pass findings to implementation stage

### During Implementation
1. Spawn the implementer subagent
2. Provide it with:
   - Feature specification (from user)
   - Architecture findings (from researcher)
   - Existing code patterns
3. Have it write the code

### Before Merge
1. Spawn security-reviewer and performance-reviewer in parallel
2. Both are read-only (no Write access)
3. Collect findings
4. Report to user before committing

## Example: Add Payment System

User: "Add Stripe integration"

→ Researcher explores payment-related code
→ Implementer writes integration based on findings
→ Security-reviewer checks for token leakage
→ Performance-reviewer checks database queries
→ User reviews all findings and decides to merge
