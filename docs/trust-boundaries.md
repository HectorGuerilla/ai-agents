# Trust boundaries and runtime behavior

This note summarizes what the toolkit is expected to do on a user's machine after installation. It is intentionally short and operational: a new user can read it before installing, and a reviewer can use it as a checklist when plugin behavior changes.

## Install-time boundary

- The `project-toolkit@ai-agents` plugin does **not** register Claude Code or Copilot CLI hooks. No hook runtime is expected to run during install or in a session.
- Installation copies agents, skills, references, and supporting scripts into the tool-specific locations used by Claude Code, Copilot CLI, and VS Code Copilot Chat.
- Some skills execute local Python helpers only when the user invokes the corresponding workflow. Those helpers require Python 3.10 or later on `PATH`.

## Session-time boundary

- Agents and skills operate inside the user's existing AI-tool session and inherit that tool's permissions, working directory, model access, and command approvals.
- The orchestrator coordinates handoffs between specialist agents; it should not be treated as an isolation boundary between agents.
- The security, QA, critic, and review gates improve process discipline, but they are not a sandbox and do not replace repository, CI, or operating-system controls.

## Files and sensitive data

- Do not paste secrets, private keys, production credentials, or regulated data into prompts unless the surrounding AI tool and organizational policy explicitly allow it.
- Treat generated plans, PR bodies, comments, and memory artifacts as project artifacts: review them before publishing or committing.
- Optional cross-session memory via Serena can persist context beyond one chat. Enable it only where persistent project memory is acceptable.

## Network and third-party services

- The toolkit depends on the host AI tools and any services they call. This repository does not provide a separate network proxy or data-retention boundary.
- When a workflow touches GitHub, package registries, CI, or deployment systems, use the same least-privilege tokens and review practices you would use for a human-operated CLI.

## Review checklist for future changes

When changing agents, skills, hooks, memory behavior, or helper scripts, update this note if any answer changes:

1. Does installation start any hook or background process?
2. Which local interpreters or binaries can be executed by skills?
3. What user files can a workflow read or write?
4. Can context persist across sessions, and where?
5. Which external services can a workflow contact through the host tool?
6. Which behavior relies on process discipline rather than technical isolation?

Clear answers here help users adopt the toolkit with the right expectations and help reviewers notice when trust boundaries move.
