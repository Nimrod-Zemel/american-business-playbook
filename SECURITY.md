# Security

A skill is code and instructions that run inside someone else's agent, next to their email and their files. This page says what this one can do, how to check that yourself, and where the protection stops.

## What the skill sees, and where it sends it

**It sends nothing anywhere.** The engine has no network access: no networking module is imported, and a test fails the build if one ever is.

| Question | Answer | Check it |
|---|---|---|
| Does it use the network? | No | `python3 tools/audit.py` |
| Does it start other programs? | No. No `subprocess`, no `os.system`, no `eval` or `exec` | `python3 tools/audit.py` |
| Does it read environment variables or credentials? | No | `python3 tools/audit.py` |
| Does it install hooks, MCP servers, agents or settings? | No such file exists in the package | `python3 tools/audit.py` |
| What does it read? | Its own `data/*.json` and `seal.json`, plus the file or text you hand it (`--file`, `--source`, `--in`, stdin) | `docs/AUDIT.md` |
| What does it write? | The engine writes one file, only when asked: `cadence --ics <path>`. The draft, the founder's own material and a talk track that the agent saves for checking (`draft.txt`, `rewrite.txt`, `source.txt`, `talk.txt`) are the agent's own working files | `docs/AUDIT.md` |
| Does it keep anything? | No. No log, no cache, no state between runs, no bytecode | `tests/test_cli.py` |
| What does it depend on? | The Python standard library, 3.9 or newer | `tests/test_security.py` |
| What may the agent do? | `allowed-tools` in `SKILL.md` grants three things: Python, to run the engine. Read, for the bundled references. Write, to save a draft or a talk track so the engine can check it | `SKILL.md` |
| Can a founder's answer become a command? | No. See "Lines the engine prints" below | `tests/test_interview.py` |
| Can look-alike characters hide in the code? | No. The engine's code is plain ASCII. Every Hebrew word it prints is data in `data/*.json` | `tests/test_security.py` |

The audit is static: it reads the source and executes nothing. `tests/test_security.py` then plants a socket import, a subprocess call, an environment read, a hidden character, a hook file and an unknown URL in a copy of the skill and asserts that each one is caught.

What the founder tells the model (names, quotes, deal details) goes wherever the host agent already sends a conversation. The skill adds no destination of its own.

## Lines the engine prints

`interview` prints command lines for the agent to run as written, and the founder's answers travel inside them. That makes the answers input to a shell, so the engine treats them as hostile:

- An answer that becomes an argument (a city, a date) is collapsed to one line and single-quoted unless it is made only of plain characters. `Boston; rm -rf ~` reaches `send-time` as one argument and is refused there as an unknown city.
- A fact sheet is printed as JSON on a single line inside a quoted heredoc. A line break in an answer is escaped by the JSON encoding, so an answer cannot close the heredoc early and nothing in it is expanded by the shell.
- Text the founder pasted (their own material for the figure check, a talk track) is printed indented, for the agent to save to a file. It is never part of a command line.
- The engine itself executes nothing. It only prints.

`tests/test_interview.py` feeds it command separators, command substitution, backticks, quotes and line breaks and parses the printed line back with a shell tokenizer. `tools/mutation_check.py` removes the quoting and confirms a test fails.

## Independent scan

The self-audit above is this project checking itself. A second opinion: the skill folder was scanned with [skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) 2.3.2 by Cisco AI Defense, with its static, bytecode, pipeline, correlation and behavioral analyzers. No model and no network were involved.

| Policy | Verdict | Findings |
|---|---|---|
| `balanced` | Safe | 1, low severity |
| `strict` | Safe | 2, low severity |

The findings, and why they stand:

- **`ALLOWED_TOOLS_GREP_VIOLATION` (low).** The engine matches phrases with Python's `re` module. The scanner reads that as searching and expects the Grep tool in `allowed-tools`. The skill never asks the agent to use Grep, so it is not declared. Adding it would widen what the agent may do only to quiet a scanner.
- **`MANIFEST_DESCRIPTION_TOO_LONG` (low, `strict` only).** The description is 980 characters. The Agent Skills limit is 1,024, and the strict policy draws its line at 512. The description is kept word for word from 1.1.0 so the skill still triggers on the same requests.

Two findings from earlier scans were fixed and not argued with. The scanner flagged that the instructions read and write files while `allowed-tools` did not say so: it now does. Under `strict` it flagged Hebrew string literals in the engine's code as a look-alike risk: the strings moved into the rule tables, and a test now keeps the code ASCII only.

A scan is a snapshot of one version by one tool. It is evidence, not a guarantee. Run your own:

```bash
pip install cisco-ai-skill-scanner
skill-scanner scan --use-behavioral --policy strict skills/american-business-playbook
```

## Integrity seal

`seal.json` lists a sha256 for every shipped file. `scripts/playbook.py` verifies it before it imports any other part of the engine, and refuses to answer (exit code 3) when:

- a listed file changed,
- a listed file is missing,
- a file that is not listed appears under `scripts/` or `data/`, or any `.py` file appears anywhere.

The last rule matters because Python imports from the script's own folder first. A planted `scripts/json.py` would otherwise run in place of the standard library. The entry point also takes its own folder off the import path before loading the standard library, so such a file cannot execute even when the seal check is waved through with `--unsealed`.

The seal covers source files, and Python normally runs a cached `__pycache__/*.pyc` in place of the source next to it. A planted `.pyc` would therefore run under a seal that still says ok. The entry point switches cached bytecode off for the engine's own modules, so every run compiles the source the seal just checked. `tests/test_security.py` plants such a file, shows that plain Python runs it, and shows that the engine does not.

`SKILL.md` and `SKILL_HE.md` are sealed by their body. Some hosts rewrite the frontmatter on install, and that must not break the seal. A changed instruction body does.

### What the seal does not do

It detects change. It is not a signature.

- Someone who can edit the files can also rewrite `seal.json`, or the checker itself. The seal catches accidents, partial edits, planted files and an agent that modifies the skill mid-session. It does not stop a person who replaces the whole package.
- A model can be talked into passing `--unsealed`. The answer is then stamped `seal BROKEN`, and the instructions tell the model to stop and report. That is a tripwire, not a wall.

For the whole-package case, use the release provenance below.

## Release provenance

Releases are built by GitHub Actions from a tagged commit. The build is reproducible (sorted entries, fixed timestamps), so the same tree always gives the same bytes. Each release carries a signed build-provenance attestation.

```bash
gh attestation verify american-business-playbook.zip --repo Nimrod-Zemel/american-business-playbook
sha256sum -c SHA256SUMS
```

The first command proves the file was built by this repository's release workflow. The second only proves the download is intact.

Install from a release. A copy forwarded in a chat has neither guarantee.

## Supply chain

- No third-party packages, at runtime or in the tests.
- GitHub Actions are pinned to full commit hashes, not to tags. Dependabot proposes updated pins once a month.
- Workflows run with `contents: read`. Only the release job gets more: `contents: write` to publish, `id-token` and `attestations` to sign.
- Checkouts do not keep credentials (`persist-credentials: false`).
- The guide in `docs/guide/` is a Word file. `tools/guide.py` reads it as a zip of XML with the standard library and executes nothing in it. The file and the tool live in the repository only. Neither is in the package a founder installs.

## Credits and licenses

The project is licensed under Apache-2.0. `LICENSE.txt` and `NOTICE.txt` travel inside the package. One module, the seal, is adapted from another project and says so in its header. Every source, its license and its commit are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and `tools/notices.py` fails the build when that record and the tree disagree.

## People named in the skill

The bench names Dan Launchpad team members. It holds public professional information only and no contact details, and the engine caps bench mentions at two per conversation. The model is told never to put words in their mouth. To run the skill for another program, replace `data/bench.json` or set `"enabled": false`, then reseal.

## Reporting a problem

Use GitHub's private vulnerability reporting: the **Security** tab of this repository, then **Report a vulnerability**. Please do not open a public issue for a security problem.

Useful in a report: the version (`python3 scripts/playbook.py --version`), the stamp line from the output, and the smallest input that shows the problem.

Supported: the latest release.
