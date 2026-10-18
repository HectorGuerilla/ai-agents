---
id: ADR-119
status: proposed
date: 2026-10-17
decision-makers: [rjmurillo]
supersedes: []
superseded-by: null
explainer: null
implemented: true
review-by: 2027-04-17
---

# ADR-119: Symlink the Agent and Skill Dogfood Trees to the Plugin Tree

## Status

Proposed. This record amends ADR-109 and ADR-108; see Related Decisions.

## Context

ADR-109 renders every shipped artifact into a plugin tree under `src/claude/`. A binplace step then copies that tree byte for byte into `.claude/`, the tree this repository loads for its own sessions. The copy is how the repository dogfoods what it ships.

For agents and skills, the copy had two costs.

1. **Two copies could disagree.** `.claude/agents/<name>.md` and `src/claude/agents/<name>.md` held the same bytes in two places. A missed `build_all.py` run left them apart until `Generated Artifact Staleness` caught it.
2. **Skill support files flowed backwards.** A skill's `SKILL.md` rendered into `src/claude/skills/<name>/` and was copied to `.claude/`. Its scripts, references, and tests went the other way: hand-maintained under `.claude/skills/<name>/`, mirrored into `src/claude/` by `sync_claude_plugin_skill_support`. One directory had two owners.

At commit `28eb90c9e` (2026-10-17), `.claude/skills/` held 104 shipped skill directories with 649 tracked files, and `.claude/agents/` held 30 agent files. All 679 were byte-identical second copies of `src/claude/` files.

The owner directed on 2026-10-17: stop copying the dogfood agents and skills; symlink them back to `src/` so they can never be out of date.

## Decision Drivers

Ranked.

1. One source of truth: an edit lands in exactly one file.
2. Harness parity: Claude Code must load the linked agents and skills exactly as it loaded the copies.
3. Containment (CWE-22, CWE-59): no link may carry a write or a trust decision outside the validated tree.
4. Dogfood fidelity: the repository should run the shipped plugin layout, so a shipped defect shows up here first.
5. Windows contributors can still check out and build.
6. Reversibility.

## Decision

1. A binplace manifest row may set `link: true` (`templates/platforms/binplace.yaml`). For such a row, binplace makes each top-level entry of `plugin_tree` a relative symlink of the same name under `install_tree`, and copies no bytes. `build/scripts/binplace_links.py` implements it.
2. The `agents` and `skills` rows set `link: true`. `.claude/agents/<name>.md` links to `../../src/claude/agents/<name>.md`. `.claude/skills/<name>` links to `../../src/claude/skills/<name>` for each shipped skill.
3. A shipped skill's support files are hand-maintained in `src/claude/skills/<name>/`. `SKILL.md` still renders from `templates/skills/<name>.SKILL.md.tmpl`.
4. A repo-local skill (`metadata.distribution: repo-local`) has no plugin copy. It stays a real directory under `.claude/skills/<name>/`, and binplace never links it.
5. The `.claude/`-to-`src/` support-file mirror is retired. `sync_claude_plugin_skill_support` now only removes a stale plugin copy of a skill that became repo-local. It refuses while `.claude/skills/<name>` is still a link, because the plugin copy is then the only copy.
6. The `skills-sidecar` row's `install_tree` is null, since `.claude/skills/review/` is a link.
7. `.claude/agents/` leaves `build_all.OWNED_PREFIXES`. It holds only links, and the `--check` snapshot refuses a symlink under an owned prefix. Its content lives under `src/`, which stays owned.

Two sub-decisions follow from these, because without them the dogfood breaks.

8. **The portability helper moves to the plugin tree.** Skill scripts find `lib/` beside their real path, which is now `src/claude/lib/`. That directory lacked `paths.py`, so the shipped Claude plugin lacked it too. `src/claude/lib/paths.py` becomes canonical. A `lib-paths` row copies it to `.claude/lib/paths.py`, and Hermes packs gain it (`lib_render.PLUGIN_LIB_FILES`).
9. **The PR completion gate trusts base-pinned links.** `run_completion_gate.py` refused any symlinked path component, so every `.claude/skills/...` command in `pr-review-config.yaml` halted. The gate now follows a link only when the trusted remote-tracking ref holds the same mode `120000` entry, at the same path under the git toplevel, with identical link text. It keeps scanning the target, so an unpinned link behind a pinned one still halts. A link with absolute text, a link that leaves the work tree, and a chain longer than eight hops halt. The owner chose this design on 2026-10-17.

## Rationale

Drivers 1 and 4 decide the mechanism: a link has no second copy to go stale, and it makes this repository execute `src/claude/` exactly as an installed plugin does. Decision 8 is that driver paying off: the link exposed that the shipped Claude plugin had no `paths.py`.

Driver 2 is met by measurement (Prior Art). Driver 3 shapes decisions 1, 5, and 9: every link target is computed, never trusted from disk, and the gate trusts only links the base branch already holds. Driver 5 is met by CI configuration and a loud failure, not by a copy fallback (Consequences). Per-entry links, not one link for `.claude/skills/`, keep repo-local skills as real directories (decision 4).

## Safety

- Every link target is computed from the validated plugin tree. A link on disk passes only when its text equals the computed relative target.
- A plugin entry that is itself a symlink, or resolves outside the plugin tree, is refused (exit 2), so no install link chains through the plugin tree to another place.
- Binplace replaces a real directory with a link only when every file matches the plugin entry byte for byte. Otherwise it exits 2 and names the directory, so a hand edit is never lost.
- A NO-REGEN file at a link path is skipped with exit 1, the copy path's contract.
- `build_all.py --check` reports a missing link, a wrong target, a real file or directory where a link belongs, and a stale link to a removed plugin entry. Each is drift, exit 2.
- A real file under `.claude/agents/` with no plugin twin is reported as an unowned notice, not an error, as before. Claude Code would load it. No gate fails on it, because `.claude/agents/` is no longer an owned prefix.

## Alternatives Considered

- **Keep copying (status quo).** Rejected by the owner directive: 679 duplicate files can drift.
- **ADR-109 Alternative D: symlink all of `.claude/` to `src/claude/`.** ADR-109 rejected it for two reasons. (a) Containment: `--check` refused symlinked owned paths. This record removes `.claude/agents/` from the owned prefixes, keeps the `src/` content owned, moves the skill existence check to the real `src/claude/skills/<name>/` directory, and adds per-link target checks. (b) Portability: Windows checkouts and some installers do not preserve links. This record accepts that cost for contributors, fails loud when a link cannot be made, and fixes the one installer that mishandled links (`packages/ai-agents-cli/scripts/build-bundle.ts`). Linking the whole tree is still rejected, because `.claude/` also holds repo-local skills, rules, hooks, settings, and lib modules that are not in `src/claude/`.
- **Load the plugin itself instead of a mirror** (enable `project-toolkit@ai-agents` from `.claude-plugin/marketplace.json`, or `claude --plugin-dir src/claude`). Rejected. Plugin skills load under the `project-toolkit:` namespace, so every bare skill name in hooks, rules, and docs would change. An installed plugin runs from a cached copy that goes stale until reinstalled. `--plugin-dir` must be passed on every session. Copilot CLI, which reads `.claude/skills/` in this repository, gains nothing from either.
- **One link for all of `.claude/agents/`.** Rejected: per-entry links keep one code path for both rows, and a stray file in `.claude/agents/` stays visible as unowned instead of landing in the plugin tree.
- **Link `.github/agents/` to `src/copilot-cli/agents/`.** Not possible. GitHub rejects a `model:` field in `.github/agents/` (issue #4938), so `templates/platforms/github.yaml` renders that tree separately.
- **Link `.github/instructions/` to `src/copilot-cli/instructions/`.** Not possible. The in-repo tree keeps `.claude/**` globs the shipped tree drops (`keepInternalGlobsFor`).
- **Link `.agents/` for Codex.** Not needed. `.agents/plugins/marketplace.json` already sources `./src/codex` directly.

## Prior Art Investigation

The copy existed because ADR-108 and ADR-109 built the template pipeline on a `.claude/` tree that was then the hand-maintained source, and ADR-109 Alternative D found the containment checks would refuse links. Those checks still exist and are adapted, not removed (Safety).

`memory_enhancement` at the repository root is a tracked symlink to `scripts/memory_enhancement` (git mode `120000`); `scripts/validation/tracked_paths.py` already resolves paths through tracked links.

Copilot CLI loading of a linked skill directory in this checkout is unverified and accepted; the shipped Copilot plugin (`src/copilot-cli/`) holds no links. Claude Code 2.1.302 loads a symlinked skill directory and a symlinked agent file. Probe on 2026-10-17 in a scratch repository: with `.claude/skills/zebra-probe` and `.claude/agents/walrus-probe.md` as relative links into `src/claude/`, `claude -p` listed both. Negative control: with the links removed, it listed neither.

## Consequences

### Positive

- An agent or skill edit lands in one place. `.claude/` cannot hold stale agent or skill content.
- 679 duplicate tracked files leave the tree: 649 skill files are deleted and 30 agent files become links, for 134 new link entries (135 in the index with `memory_enhancement`). `.claude/skills/` keeps 121 entries: 104 shipped links and 17 repo-local directories.
- The dogfood now runs the shipped layout. It surfaced and fixed three shipped defects: the Claude plugin had no `lib/paths.py`, the npm bundler dropped linked skills (92 files bundled instead of 642), and several scanners counted both copies.

### Negative

- **Git paths.** Git refuses a path beyond a symlink: `git add .claude/skills/adr-review/SKILL.md` fails with `pathspec ... is beyond a symbolic link`. Editing through `.claude/` works; git commands must name `src/claude/skills/...`. Rule and guide text now names `src/claude/skills/<name>/` as the edit location.
- **Resolved paths.** `Path(__file__).resolve()` in a skill script now lands under `src/claude/skills/`, one directory deeper, and its sibling `lib/` is `src/claude/lib/`.
- **Enumerators.** `Path.rglob`, `os.walk`, and `git ls-files` do not descend into a linked directory. A gate that enumerated `.claude/skills` silently scanned only repo-local skills until it was pointed at `src/claude/skills`.
- **CI path filters.** A support-file edit appears in a diff only under `src/claude/`. Filters, `labeler.yml`, `CODEOWNERS`, and `scripts/ci/path_policy.yml` now name `src/claude/skills` or `src/claude/agents` beside each `.claude/` pattern.
- **Windows.** A checkout needs `core.symlinks=true` and symlink privilege (Developer Mode). Without them git writes each link as a text file holding its target, and `build_all.py --check` reports drift. Creating a link without privilege exits 2 with a message naming both settings. The two Windows CI jobs that read `.claude/` (`cli-smoke.yml`, the `test-windows-pwsh` job in `pytest.yml`) set `core.symlinks` before checkout.
- **Gate transition window.** Decision 9 pins links from the trusted ref. Until a new link reaches `origin/main`, the completion gate halts for any criterion that reaches it through `.claude/`. That includes the PR that introduces this record, and any PR that adds a skill or agent. Remedies: pass `--config src/claude/skills/pr-review/pr-review-config.yaml` (byte-identical at the base), or record the reviewed one-time override. Fetch `origin` after the merge.
- **Known gate debt.** The completion gate's module and dynamic-load resolvers do not all return the post-link path. A criterion that imports through a pinned link can halt as untrusted. This fails closed, so the cost is a false halt, not a bypass.
- **Coverage.** `coverage.py` records the real path, so `src/claude` joins `[tool.coverage.run] source`, and the REQ-009 gate's `--include` names the `src/claude/skills/...` path.

### Neutral

- `.claude/rules/`, `.claude/hooks/`, and `.claude/lib/` remain byte copies. The same `link: true` flag can cover them in a later change.

## Impact on Dependent Components

- `build/scripts/binplace_manifest.py`: reads `link`, folds link outcomes into `BinplaceResult`, allowlists link paths, and on a copy row unlinks a leftover top-level install link (rollback).
- `build/scripts/skill_templates.py`: a shipped skill's existence check moves to `src/claude/skills/<name>/`; `owned_targets` returns only the path `compile_all` writes.
- `build/scripts/skill_support_mirror.py`: the copy mirror is removed.
- `build/scripts/build_all.py`: `.claude/agents/` leaves `OWNED_PREFIXES`.
- `build/scripts/lib_render.py`: Hermes packs include `paths.py`.
- `build/scripts/check_surface_parity.py`: a binplace row whose `source` is its `plugin_tree` may describe that tree as `independent`.
- `templates/platforms/copilot-cli.yaml` and `codex.yaml`: `sourceDir` reads `src/claude/skills`, the real directory.
- `src/claude/skills/github/scripts/pr/run_completion_gate.py`: decision 9.
- `packages/ai-agents-cli/scripts/build-bundle.ts`: follows links when it bundles `.claude/`.
- Repository scanners and ratchets that enumerated `.claude/skills` scan `src/claude/skills` once. Several counted both copies before, so their baselines moved down only.
- `scripts/validation/adr_cited_paths.py`: a cited path under a tracked link exists when its target is tracked.

## Reversibility Assessment

Reversible in one change set, with these steps.

1. Remove `link: true` from the `agents` and `skills` rows and run `build_all.py`. The copy path unlinks each leftover top-level install link, then copies real files; `--check` reports any link it finds on a copy row as drift (`test_dropping_link_true_restores_real_directories`).
2. Restore from history: the support-file mirror in `skill_support_mirror.py`, `.claude/agents/` in `OWNED_PREFIXES`, the `skills-sidecar` install tree, the `.claude/skills/<name>/` existence check in `skill_templates.py`, the `sourceDir` values in `copilot-cli.yaml` and `codex.yaml`, and the scanner roots and baselines.
3. Decision 9 and decision 8 may stay: with no links, the gate meets no link, and `src/claude/lib/paths.py` fixes the shipped plugin regardless.

## Related Decisions

- ADR-109 (template-first plugin distribution): amended. Its Alternative D is adopted for agents and skills, and its 2026-09-15 support-file amendment is retired for shipped skills. Both carry a dated note pointing here.
- ADR-108 (template-owned skill files): amended. The not-a-symlink existence check applies to `src/claude/skills/<name>/` for shipped skills. It carries a dated note pointing here.
- ADR-052: superseded by ADR-109; unchanged.

## Review

Revisit by 2027-04-17, or sooner if a harness stops loading symlinked skills or agents.

## Consensus

See `.project-toolkit/critique/ADR-119-debate-log.md`.

## References

- `build/scripts/binplace_links.py`, `templates/platforms/binplace.yaml`.
- `tests/build_scripts/test_binplace_links.py`, `tests/skills/github/test_run_completion_gate.py` (`TestPinnedLinkTrust`).
