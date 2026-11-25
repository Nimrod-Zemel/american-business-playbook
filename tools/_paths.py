"""Shared paths for the maintainer tools. Not shipped inside the skill package."""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_NAME = "american-business-playbook"
SKILL = os.path.join(REPO, "skills", SKILL_NAME)
SCRIPTS = os.path.join(SKILL, "scripts")

sys.dont_write_bytecode = True
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
