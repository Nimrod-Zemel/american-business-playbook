# Releasing

For the maintainer: from a folder on disk to a signed release that a founder can install. No Git background is assumed.

[עברית בהמשך הדף](#hebrew)

## First publication

Before the first push, one decision that is not technical: the guide in `docs/guide/` becomes public with the repository. It is a joint work with Dan Launchpad, so publish it with their agreement, and read the Terms at the end of [docs/guide/README.md](guide/README.md). They say "all rights reserved" until its authors choose otherwise.

1. On GitHub, press **+**, then **New repository**. Name it `american-business-playbook`. Leave README, .gitignore and license unticked: all three are already in the folder.
2. Open a terminal inside the folder and push it:

```bash
git init -b main
git add -A
git commit -m "feat: The American Playbook 2.0.0" \
  -m "The integrity seal is adapted from founder-skills by lool ventures (Apache-2.0): https://github.com/lool-ventures/founder-skills/blob/9861bb5fcd7349805d787d298435053375e0288b/founder-skills/scripts/script_hashes.py" \
  -m "Every source and what came from it: THIRD_PARTY_NOTICES.md"
git remote add origin https://github.com/Nimrod-Zemel/american-business-playbook.git
git push -u origin main
```

Do not drag the files into the browser. The folder has hidden directories (`.github`, `.claude-plugin`) that a drag misses, and without them there are no automatic checks and no Claude Code install.

3. Open the **Actions** tab. A check named `ci` runs on seven Python versions. Wait for the green mark. If one is red, open the run and read the failing line.

## Repository settings, once

Under **Settings**:

- **Private vulnerability reporting**: switch it on (Security section). `SECURITY.md` and the README send people there.
- **Social preview** (General section): upload `assets/social-preview.png`. It is the picture a link to the repository shows in chat apps and on LinkedIn.
- **About** (the gear on the repository's front page): a one-line description, and topics such as `agent-skills`, `claude`, `claude-code`, `israel`, `startups`, `sales`, `fundraising`.
- **Two-factor authentication** on your GitHub account. Releases are signed with the repository's identity, so the account is the key.

Once a month Dependabot may open a pull request that refreshes the pinned GitHub Actions. If `ci` is green on it, merge it.

## Cutting a release

1. Set the new version in four places: `scripts/abp/__init__.py`, `metadata.json`, `.claude-plugin/plugin.json` and `CITATION.cff` (with its date). Add a section to `CHANGELOG.md`. The tests fail if one of them is forgotten.
2. Run `python3 tools/build.py`. If it ends without an error, the references, the credits, the guide, the seal and the tests agree.
3. Commit, push, and wait for `ci` to turn green.
4. Tag the commit:

```bash
git tag v2.0.0
git push origin v2.0.0
```

Without a terminal: on the repository page open **Releases**, then **Draft a new release**, type the new tag `v2.0.0` and publish.

Either way the `release` workflow runs every check again, builds the package, signs its provenance and attaches four files to the release:

| File | What it is |
|---|---|
| `american-business-playbook.zip` | The file to install in Claude |
| `american-business-playbook.skill` | The same bytes under another extension |
| `GEMINI-GEM.md` | For hosts that cannot run code |
| `SHA256SUMS` | Checksums of the two packages |

The "Source code" archives that GitHub adds on its own are not the package.

5. Optional, with the GitHub CLI installed:

```bash
gh attestation verify american-business-playbook.zip --repo Nimrod-Zemel/american-business-playbook
```

## After a release

- **Install it** as the README describes. If an older version is installed, remove it first.
- **Skills IL.** If the skill is listed there, the update is a pull request to the category repository with the contents of `skills/american-business-playbook` only. That folder has no README, as their rules require.

## When you borrow from another project

Credit is part of the build, and the build fails without it. The five steps are in [CONTRIBUTING.md](../CONTRIBUTING.md#credit-what-you-borrow).

## Changing a rule

See [CONTRIBUTING.md](../CONTRIBUTING.md). The short version: edit a JSON table under `skills/american-business-playbook/data/`, run `python3 tools/build.py`, commit.

---

<a id="hebrew"></a>

<div dir="rtl">

## עברית

למתחזק: מתיקייה על המחשב ועד גרסה חתומה שיזם יכול להתקין. בלי ידע קודם ב-Git.

### פרסום ראשון

לפני הדחיפה הראשונה, החלטה אחת שאינה טכנית: המדריך שב-`docs/guide/` הופך לציבורי יחד עם הריפו. הוא עבודה משותפת עם Dan Launchpad, ולכן מפרסמים אותו בהסכמתם. התנאים כתובים בסוף [docs/guide/README.md](guide/README.md): "כל הזכויות שמורות", עד שמחבריו יחליטו אחרת.

1. ב-GitHub לוחצים **+**, ואז **New repository**. השם: `american-business-playbook`. לא מסמנים README, לא .gitignore ולא License. שלושתם כבר בתיקייה.
2. פותחים טרמינל בתוך התיקייה ומריצים את בלוק הפקודות שמופיע למעלה תחת First publication. לא גוררים קבצים דרך הדפדפן: גרירה מפספסת את התיקיות הנסתרות (`.github`, `.claude-plugin`), ובלעדיהן אין בדיקות אוטומטיות ואין התקנה ב-Claude Code.
3. בלשונית **Actions** רצה בדיקה בשם `ci` על שבע גרסאות Python. מחכים לסימן ירוק.

### הגדרות, פעם אחת

- **Private vulnerability reporting**: להפעיל. לשם מפנים SECURITY.md וה-README.
- **Social preview**: להעלות את `assets/social-preview.png`. זו התמונה שמופיעה כשמשתפים קישור לריפו.
- **About**: תיאור בשורה אחת ונושאים (topics).
- **אימות דו-שלבי** בחשבון ה-GitHub. הגרסאות נחתמות בזהות של הריפו, ולכן החשבון הוא המפתח.

פעם בחודש Dependabot עשוי לפתוח Pull Request שמעדכן את רכיבי ה-Actions. אם `ci` ירוק עליו, מאשרים.

### הוצאת גרסה

1. מעדכנים את מספר הגרסה בארבעה מקומות: `scripts/abp/__init__.py`, `metadata.json`, `.claude-plugin/plugin.json` ו-`CITATION.cff` (כולל התאריך), ומוסיפים פסקה ל-`CHANGELOG.md`. הבדיקות נכשלות אם אחד נשכח.
2. מריצים `python3 tools/build.py`.
3. עושים commit ו-push, ומחכים ש-`ci` יהיה ירוק.
4. יוצרים תג `v2.0.0` ודוחפים אותו, או יוצרים גרסה חדשה עם התג הזה דרך **Releases** בעמוד הריפו.

התהליך `release` מריץ שוב את כל הבדיקות, בונה את החבילה, חותם על מקורה ומצרף לגרסה ארבעה קבצים. מתקינים את `american-business-playbook.zip`. קובצי "Source code" ש-GitHub מוסיף לבד הם לא החבילה.

### כשלוקחים משהו מפרויקט אחר

קרדיט הוא חלק מהבנייה, לא תוספת בסוף.

1. שורה בראש הקובץ: הערה שמתחילה ב-`THIRD-PARTY:`, השם הקצר של המקור, מה נלקח ומה שונה.
2. רשומה ב-`THIRD_PARTY_NOTICES.md`: בעל הזכויות, הרישיון, קישור, ה-commit המלא, והקובץ עם מה שנשמר ומה שהשתנה.
3. עותק של טקסט הרישיון, בלי שינוי, בתיקייה `licenses/`.
4. אזכור ב-README תחת Acknowledgments, על מה שהמקור באמת נתן.
5. קישור למקור בהודעת ה-commit.

הפקודה `python3 tools/notices.py` מכשילה את הבנייה כשקובץ מסומן לא רשום, או כשקובץ רשום איבד את הסימון.

### עדכון חוק

עורכים טבלת JSON תחת `skills/american-business-playbook/data/`, מריצים `python3 tools/build.py`, ועושים commit. הפירוט ב-[CONTRIBUTING.md](../CONTRIBUTING.md).

</div>
