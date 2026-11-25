"""American Business Playbook: the deterministic engine behind the skill.

The model interviews the founder and writes the English. This package judges:
it counts, matches, schedules and scores from the rule tables in ../../data,
so the same facts always produce the same verdict.

Standard library only. No network, no subprocess, no file writes unless the
caller passes an explicit output path.
"""

__version__ = "2.0.0"
