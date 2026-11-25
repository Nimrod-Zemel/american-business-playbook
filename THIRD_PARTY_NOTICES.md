<!-- THIRD-PARTY: gstack. The format of this file follows gstack's NOTICE.md (MIT), with this project's entries. -->
# Third-Party Notices

The American Playbook is licensed under Apache-2.0. The rules it applies come from "The American Playbook", the guide Nimrod Zemel wrote with Dan Launchpad. The guide itself is in `docs/guide/` and keeps its own terms. The engineering around those rules borrows from the projects below.

Rewriting is not an exemption. One module here is adapted code and says so in its header. The rest is ideas, conventions and formats written again from scratch, and it is credited all the same. The license text of every source is in [`licenses/`](licenses), unmodified.

`python3 tools/notices.py` checks this file against the tree on every build and in CI. A file that carries a `THIRD-PARTY:` line must be listed here. A file listed here must exist and, where its format allows, carry that line.

How to read an entry:

- **Derived, modified** is material adapted from the source, with what was kept and what was changed.
- **Ideas, not text** is a courtesy. Nothing was copied, and the idea is theirs.
- **No header** lists files that follow a convention of the source and whose format cannot carry a marker line.

## founder-skills, Copyright 2026 lool ventures, Apache License 2.0

- Source: https://github.com/lool-ventures/founder-skills
- Commit: `9861bb5fcd7349805d787d298435053375e0288b` (v0.28.0)
- License text: `licenses/Apache-2.0-lool-ventures.txt`
- Marker: `THIRD-PARTY: founder-skills`

Derived, modified:

- `skills/american-business-playbook/scripts/abp/seal.py`: adapted from `founder-skills/scripts/script_hashes.py`. Kept: the manifest shape (schema number, algorithm, line-ending rule, a map of paths to hashes), sha256 over the bytes with CRLF folded to LF, hashing a Markdown file by the body after its front matter because installers rewrite front matter, the walk that skips dot and double-underscore folders, and counting a `.py` file the manifest does not list as a difference. Changed: it seals every shipped file, where the original lists scripts and agent bodies. The check runs before the engine loads and stops it, where the original runs from a hook and reports. There is no tolerance threshold. Any unlisted file under `scripts/` or `data/` breaks the seal. The rule-table fingerprint and the refusal message are new. Writing the manifest moved out of the shipped module.
- `tools/seal.py`: the `--write`, `--check` and `--root` command line of the same file, written again around `abp.seal`.
- `README.md`: the page structure of founder-skills' `README.md` (header image and badge row, one block per mode under the same four labels, getting started, what to expect on a first run, troubleshooting, privacy, contact), its `<picture>` pattern for light and dark illustrations, and two sentence patterns: the note that the technical spec is not required reading, and the opening of the privacy section. The text and the illustrations are this project's.

Ideas, not text:

- `skills/american-business-playbook/scripts/abp/core.py`: the receipt that names every check that did not run follows founder-skills' disclosure codes (`HANDOFF_BYPASSED`, `AI_CRITERIA_SKIPPED`). The code is this project's.
- In no single file: the division of labor itself. The model supplies structured facts, and a script validates them and computes the result.

## skill-creator, Copyright 2026 Anthropic, PBC., Apache License 2.0

- Source: https://github.com/anthropics/skills (`skills/skill-creator`)
- Commit: `e4bb5d960d87126ff3b3a8af1a104b7db67560ba`
- License text: `licenses/Apache-2.0-anthropic.txt`
- Marker: `THIRD-PARTY: anthropic-skills`

Ideas, not text:

- `tools/package.py`: the `.skill` file name and the layout of the package, a zip whose single top-level entry is the skill folder, follow `scripts/package_skill.py`. The writer is this project's. It adds the stored entries and fixed timestamps that make the build reproducible.
- In no single file: the authoring guidance in skill-creator's `SKILL.md` (what belongs in the description, moving detail into `references/`, a body under 500 lines) shaped this skill's instructions.

No header:

- `evals/*/prompt.md`, `evals/*/case.yaml` and `evals/*/graders/*.md`: the case layout that `claude plugin eval` reads, as documented in the skill-creator that ships with the Claude app (`references/schemas.md`, a later version than the commit above). The cases are this project's.

The skill format itself is the open Agent Skills specification: https://agentskills.io/specification

## Skills IL, Copyright (c) 2026 Skills IL (Yootech), MIT License

- Source: https://github.com/skills-il/communication
- Commit: `cc45af1165d8fa39bb0549d4b349d57eab3f2ead`
- License text: `licenses/MIT-skills-il.txt`
- Marker: `THIRD-PARTY: skills-il`

Derived, modified:

- `tests/test_docs.py`: the nine checks of `scripts/validate-skill.sh`, written again in Python as unit tests (`AgentSkillsFormatTest`, `HebrewCompanionTest`). Three of its regular expressions are reused: the name pattern, the when-to-use pattern and the secret pattern. No shell code is included.

No header:

- `skills/american-business-playbook/SKILL_HE.md`: the Hebrew companion file is a Skills IL convention. The text is this project's.
- `skills/american-business-playbook/metadata.json`: the field layout (`display_name`, `display_description`, `tags`, `supported_agents`) used by the skills in that repository.
- `skills/american-business-playbook/optimization-log.json`: the file name and its place in the skill folder.
- `skills/american-business-playbook/SKILL.md`: the section order of Skills IL skills (Overview, Examples, Bundled Resources, Reference Links, Gotchas, Troubleshooting).

## gstack, Copyright (c) 2026 Garry Tan, MIT License

- Source: https://github.com/garrytan/gstack
- Commit: `4394a02363d6fb1acc6115927bc04ee26b78e860`
- License text: `licenses/MIT-garry-tan.txt`
- Marker: `THIRD-PARTY: gstack`

Derived, modified:

- `THIRD_PARTY_NOTICES.md`: the format of gstack's `NOTICE.md` (one entry per source with its holder and license, the link and the commit, then what was derived and how it changed) and its rule that rewriting is not an exemption. The entries are this project's.

## proof-engine, Copyright (c) 2026 Yaniv Golan, MIT License

- Source: https://github.com/yaniv-golan/proof-engine
- Commit: `e9a19b5bd41f7acbde9b6248fc2d366c7bb8657f` (v1.45.0)
- License text: `licenses/MIT-yaniv-golan.txt`
- Marker: `THIRD-PARTY: proof-engine`

Derived, modified:

- `CITATION.cff`: the field layout of proof-engine's `CITATION.cff`, with this project's values.

## Used, not distributed

Nothing in this section is copied into the repository or into the release package.

- **skill-scanner** by Cisco AI Defense (Apache-2.0), https://github.com/cisco-ai-defense/skill-scanner. Version 2.3.2 scanned the skill before release. The result is in [SECURITY.md](SECURITY.md).
- **Inter** by Rasmus Andersson (SIL Open Font License 1.1), https://rsms.me/inter/. The images under `assets/` were rendered with this typeface. The font files are not included.
- **GitHub Actions**: `actions/checkout`, `actions/setup-python` and `actions/attest-build-provenance` (MIT), referenced by commit in `.github/workflows/`.

## The content

The guide points its readers to two books. The skill links to them as further reading and quotes neither:

- Erin Meyer, *The Culture Map*: https://erinmeyer.com/
- Rob Fitzpatrick, *The Mom Test*: https://www.momtestbook.com/
