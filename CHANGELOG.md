# Changelog

## [2.0.0] - 2026-11-25

A rebuild on one principle: **the model interviews and writes, the code judges.**

In 1.1.0 the model read the playbook as prose and decided for itself what to ask and what a meeting was worth. Two small scripts counted sentences and computed dates. In 2.0.0 the questions come from a bank the engine walks, every verdict, score, count, date and send time comes from that engine, and every answer says what it did not check.

| | 1.1.0 | 2.0.0 |
|---|---|---|
| What the model must read to work | `SKILL.md` (2,579 words) plus four reference files (5,111 words) | `SKILL.md` (2,583 words). References are generated and optional |
| Who decides what to ask the founder | The model | `interview`, from a bank of 117 questions |
| Who decides Green, Yellow or Red | The model | `decode` |
| Who scores a simulation | The model | `debrief` |
| Engine | 2 scripts, 434 lines | 14 commands, 4,654 lines, standard library only |
| Where the rules live | Prose in 4 reference files | 10 JSON rule tables, 490 phrase patterns |
| The guide itself | Not in the repository | `docs/guide/`, checked against the tables on every build |
| Tests | None in the package | 517 unit tests, Python 3.9 to 3.15 |
| Proof of what ran | None | A stamp on every answer |
| License | MIT | Apache-2.0, with every source credited in `THIRD_PARTY_NOTICES.md` |

### Added

- `interview`: the skill asks before it judges, writes or simulates, and the engine decides what it asks. A bank of 117 questions in 11 areas (`data/interview.json`), each with its reason in both languages and the fact it fills. At most three a turn, musts first, and only what applies: by mode, by who the American is, by the kind of email, by earlier answers. It prints the picture so far, the guide's cautions that the answers trigger, and the commands to run with their fact sheets already built. Once the musts are in the founder gets an answer and the interview goes on. `"stop": true` ends it, and the stamp names what was left open.
- The interview asks for bad news by name. Every Yellow and Red signal of the traffic light is either probed by a question or raised by the decoder from the lines the interview collects, and a test holds that line.
- In email mode, what the founder says in the interview is the source the figures are checked against. A number that came from nowhere still stops the email. A number the founder gave three questions ago does not.
- The guide is in the repository: `docs/guide/` holds The American Playbook V2 as its authors wrote it, and a reading copy generated from it. `tools/guide.py` fails the build when the Word file changes without the tables, when the reading copy is stale, or when the guide quotes an English line that no rule table has. Its first run found 30 such lines. They are in now.
- Module 6 of the guide, politics: six rows in the decoder (what was said, what it is, the move), the iron rule and the bridge line in every prep sheet, `scene --politics` to rehearse staying out of it, and a debrief that reports whether the founder bridged, stayed out or joined.
- Module 5, in the room: the opening frame, the hard stop at minute 28, the small-talk bridge and the "How are you?" answer, turn-taking and the enthusiasm gap, in every prep sheet. Module 8: punctuality, scheduling ahead, formal stages and hierarchy.
- `decode`: the traffic-light verdict. It withholds a verdict until it has the American's exact words, the next step and who proposed it, and what the meeting cost the other side. A date only the founder proposed does not count as commitment.
- `prep`, `guard`, `scene`, `debrief`: prep sheets per meeting type, a check for moves that burn a meeting (BANT aimed at an investor, forbidden topics, trashing a competitor), repeatable simulation scenes, and a scored debrief with Israeli-isms next to their American phrasing.
- `lint`: 22 checks that can raise 33 distinct findings. 1.1.0 had 9 checks. New ones include command tone, the opener, generic subjects, hurt or nudging follow-ups, unresolved brackets, and figures that do not appear in the founder's own material (a must-fix when a source is given).
- `send-time`: the next send moments in the recipient's morning window, on both clocks, around four holiday windows and eleven federal holidays.
- `template`: the guide's 15 templates with named slots. An unfilled slot stays a bracket, and a bracket fails the lint.
- `intro`, `bench`, `schema`, `doctor`.
- A receipt on every answer: engine version, a fingerprint of the rule tables, the checks that were skipped and the assumptions made.
- An integrity seal, a static self-audit, a reproducible release package and signed build provenance.
- `docs/ASSUMPTIONS.md`: every place where the guide is qualitative and the code needed a number.
- `docs/EXAMPLES.md`: real engine output for fixed inputs, regenerated on every build.
- 9 model-level eval cases in `evals/`, one of them for a founder who says: enough questions.
- `tools/mutation_check.py`: breaks 49 rules one at a time and checks that a test fails. 48 are caught. The 49th changes nothing a caller can observe, because the input is rejected earlier. The first run with the interview in found one hole: making the date of a next step optional failed no test. The musts are now pinned by name.
- `THIRD_PARTY_NOTICES.md`, `licenses/`, `NOTICE` and `CITATION.cff`: every source this version borrows from, with its holder, license, link and commit, and what came from it. `tools/notices.py` fails the build when a file carries a source marker and is not listed, or is listed and lost its marker.
- One README in two languages: English first and written for the founder, Hebrew after it. Original illustrations, a first-run guide, troubleshooting and a privacy section. `docs/RELEASING.md` walks the maintainer from a folder to a signed release, in both languages.
- Issue forms for a rule that feels wrong and for a bug, a pull request checklist, and `CODEOWNERS`.

### Changed

- The license is Apache-2.0. Version 1.1.0 was MIT. `LICENSE.txt` and `NOTICE.txt` now travel inside the package.
- The playbook moved from prose into rule tables under `data/`. The reference files are generated from those tables.
- `email-linter.py` and `followup-scheduler.py` are replaced by `playbook.py lint` and `playbook.py cadence`.
- Time zones are computed by the engine and no longer need the host's time zone database.
- `GEMINI-GEM.md` is generated and ships with each release, no longer inside the skill folder. It carries the manual protocol and marks every answer `NOT VERIFIED BY CODE`.
- Single federal holidays are skipped as send dates by default. With that switch off, the cadence matches 1.1.0 exactly on 1,096 consecutive meeting dates. With it on, 55 of those dates move.
- An investor's soft pass now gets the bar-extraction reply and then the monthly update, not the sales breakup email.
- The engine reads stdin only when asked to (`--file -`, `--in -`). A run that was given no input fails at once with a hint, where a default read would hang on hosts that leave the stream open.

### Fixed

Defects in the 1.1.0 scripts, found while porting them. Each has a test.

- The linter dropped a one-line email that opened with a greeting ("Hi Michael - ...") and reported 0 sentences, 0 words and "no question found". The guide's own value-bump and second-angle templates hit this.
- Four of the guide's templates (breakup, recap, second angle, bar extraction) failed the linter's softener rule.
- A question quoted inside a sentence was counted as a second ask.
- The scheduler failed with `ZoneInfoNotFoundError` on hosts without a time zone database.

### Security

- Standard library only. No network, no subprocess, no environment reads, one optional file write.
- The seal is verified before the engine loads. A file planted under a standard-library name does not run, and neither does planted bytecode.
- GitHub Actions pinned to commit hashes, refreshed monthly by Dependabot. The release job is the only one with write permissions.
- The engine's code is plain ASCII. Every Hebrew word it prints is data in the rule tables, so a look-alike character has nowhere to hide in code.
- `allowed-tools` names everything the instructions use: Python, Read and Write.
- Scanned with Cisco AI Defense's skill-scanner 2.3.2: safe under its `balanced` and `strict` policies, with two low-severity findings that `SECURITY.md` lists and explains.

### Kept

The description and its trigger phrases, the three modes, Hebrew coaching with English deliverables, the no-dashes rule, the simulation-start exception, the bench and its rules. Of the 110 quoted lines in the 1.1.0 files, 108 are present verbatim. One was reworded, and one was the name of an error that can no longer occur.

### Not done

- Model-level evals were not re-run. The 1.1.0 benchmark (24 of 25 with the skill, 21 of 25 without) describes the old instructions and is not claimed for this version.
- The GitHub workflows were validated as YAML and their steps were run locally. They have not run on GitHub yet.
- The skill was not tried in agents other than Claude.

## [1.1.0] - 2026-08-05

- Merged the parallel `american-playbook` skill into this one to end a trigger collision.
- Added the no-invented-facts rule, the intro economy, seven email templates, advanced investor communication and the simulation-start exception.
- Benchmark against a no-skill baseline: 24 of 25 assertions, against 21 of 25.

Details: `skills/american-business-playbook/optimization-log.json`.
