# Contributing

Most changes to this skill are changes to a rule: a new soft-no phrase, a different threshold, a better template. Rules live in JSON, so most contributions need no Python.

## The loop

```bash
# 1. edit a rule table
$EDITOR skills/american-business-playbook/data/decoder.json

# 2. rebuild: references, self-audit, credits, guide, seal, tests
python3 tools/build.py

# 3. read what changed in the generated files, then commit everything
git diff docs/EXAMPLES.md
```

`tools/build.py` runs seven steps in order, because each depends on the one before: generate the references from the tables, audit, check the credits, check the tables against the guide, write the seal, run the tests, and (with `--package`) build the release file. Nothing needs installing. Python 3.9 or newer is enough.

CI runs the same checks on Python 3.9 to 3.15 and fails if the seal, the generated files, the audit, the credits or the guide do not match the tree.

## Where things live

| You want to change | Edit |
|---|---|
| A phrase an American says, what it means, the counter-move | `data/decoder.json` |
| The traffic-light signals, thresholds, decision rules, intake questions | `data/signals.json` |
| Email limits, softeners, pushy words, lint messages | `data/email.json` |
| An email template | `data/templates.json` |
| The cadence, the send window, holiday windows, cities | `data/cadence.json` |
| Prep sheets, guards, Israeli-isms, characters, the debrief rubric | `data/meetings.json` |
| The bench (people, routing) | `data/bench.json` |
| Intro etiquette | `data/intro.json` |
| A question the skill asks the founder, its reason, when it applies, what it feeds | `data/interview.json` |
| Labels, the stamp, the manual-mode protocol | `data/coach.json` |
| What the model is told | `SKILL.md` and `SKILL_HE.md`, together |

Never edit a file under `references/`, `docs/ASSUMPTIONS.md`, `docs/EXAMPLES.md`, `docs/AUDIT.md`, `dist/GEMINI-GEM.md` or the reading copy in `docs/guide/`. They are generated, and the build overwrites them.

## A question for the bank

A question earns its place by what it does with the answer. In `data/interview.json` each one says:

- `level`: per mode, 1 (the engine cannot work without it), 2 (it sharpens the answer) or 3 (depth). Add a must only when a command truly cannot run without the fact. A must delays every founder.
- `when`: the earlier answers that make it relevant. A question that does not apply is never asked.
- `feeds`: the field of a fact sheet it fills, the argument it sets, or the founder's own material it becomes. A question with no feed is handed to the model as context for its writing, and that is fine when it is true.
- `why`, in both languages: one or two short sentences the model can say out loud. If it restates a rule of the guide, name the module in `guide_module`.
- `eases`: the earlier answer that makes a must unnecessary (a pasted draft answers for the ask and the proof).

`python3 skills/american-business-playbook/scripts/playbook.py doctor` and the tests reject a question that feeds a field no command has, depends on a later question, or lacks its reason in either language.

## When the guide changes

The Word file in `docs/guide/` is the source. Replace it, run `python3 tools/guide.py`, and add whatever it reports as missing to the tables, each line with a test. Then update the version and the hash under `guide` in `data/coach.json` and run the build. The steps, and what the check covers, are in [docs/guide/README.md](docs/guide/README.md).

## Phrase patterns

Tables match text with a small syntax, written the way the phrase is spoken:

| Pattern | Matches |
|---|---|
| `keep us\|me posted\|updated` | alternatives inside one word position |
| `?really interesting` | a leading `?` makes that word optional |
| `send me ... deck` | `...` allows up to five words in between |
| `integrat*` | a trailing `*` matches any ending |
| `re:\bq[1-4]\b` | escape hatch: a raw regular expression |

Text and patterns are normalized the same way before matching: lowercase, apostrophes dropped, other punctuation turned into spaces. Matching is on whole words.

Two mistakes the table tests catch:

- An alternative must be a single word. `we'll|we will be in touch` is wrong. Write two patterns.
- A decoder row must match its own wording and every example listed with it, and the plain business sentences in `non_examples` must match no row.

## Rules for a rule

1. **Tag the origin.** `"origin": "playbook"` if it is in the Dan Launchpad guide, `"origin": "extension"` if you quantified or added it. Extensions are listed in `docs/ASSUMPTIONS.md` automatically.
2. **Both languages.** Every coaching string has `en` and `he`. English deliverables (templates, counter-lines) stay English.
3. **A test for every rule.** A new decoder row needs a case in `tests/test_decode.py`. A new lint check needs a passing and a failing draft in `tests/test_mail.py`.
4. **No em dashes or en dashes**, anywhere, in either language. The tests check.
5. **The model does not judge.** If a change asks the model to weigh, rank or score something, move that into the engine or do not make the change.

## Engine changes

- Standard library only, and only the modules already imported. `tools/audit.py` has the allowlist. Adding to it needs a reason in the pull request.
- No network, no subprocess, no environment reads, no file writes beyond `cadence --ics`.
- Python 3.9 syntax.
- Every command prints a receipt. A check that did not run is recorded with `receipt.skip(name, why)` so it shows up in the stamp.
- New command or flag: add it to `SKILL.md` and `SKILL_HE.md`. `tests/test_docs.py` fails if the instructions and the engine disagree.

## Credit what you borrow

Rewriting is not an exemption. If a change adapts code, a format or a convention from another project, the credit ships in the same commit:

1. A line at the top of the file: a comment that starts with `THIRD-PARTY:`, then the source's short name, then what was taken and what was changed.
2. The source's entry in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): holder, license, link, the full commit, and the file with what was kept and what was changed. An idea with no text taken goes under "Ideas, not text".
3. The source's license text, unmodified, in `licenses/`.
4. A line in the README under Acknowledgments, for what the source actually gave. Credit that is larger than the debt reads as name-dropping.
5. A link to the source in the commit message.

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/): `feat(interview): ask a recap what was agreed`, `fix(data): "circle back" also matches "get back to you"`, `docs: ...`. The scope is the part a reader would look for: `engine`, `data`, `interview`, `guide`, `docs`, `ci`.

`python3 tools/notices.py` fails the build when a marked file is not listed, a listed file lost its marker, a commit is not a full hash, or a license text is missing.

## Do the tests still bite?

```bash
python3 tools/mutation_check.py
```

It breaks one rule at a time in a copy of the repository (a threshold, a decision rule, a daylight-saving date, the seal check) and reports whether the suite noticed. It takes several minutes, so CI does not run it. Run it before a release that touches the engine, and add a mutation when you add a rule.

## Versions and releases

The version lives in four places that the tests keep in step: `scripts/abp/__init__.py`, `metadata.json`, `.claude-plugin/plugin.json` and `CITATION.cff`. Add a section to `CHANGELOG.md`, run the build, commit, then tag:

```bash
git tag v2.0.1 && git push origin v2.0.1
```

The release workflow rebuilds, re-checks, packages, signs the provenance attestation and publishes. The full walk-through, in English and Hebrew: [docs/RELEASING.md](docs/RELEASING.md).

## Model-level evals

`evals/` holds cases for `claude plugin eval`. They call a model and cost money, so CI does not run them. Run them before a release that changes `SKILL.md`:

```bash
claude plugin eval . --allow-tools Write,Edit,Bash
```

## License of contributions

The project is licensed under [Apache 2.0](LICENSE). A contribution you send is offered under the same license. The guide in `docs/guide/` is not part of that: it keeps its own terms and is changed only by its authors.

## Security problems

Not here. See [SECURITY.md](SECURITY.md).
