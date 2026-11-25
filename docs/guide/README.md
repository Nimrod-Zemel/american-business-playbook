# The guide behind the skill

The skill does not invent its rules. They come from **The American Playbook**, the guide Nimrod Zemel wrote with Dan Launchpad for founders in the program. This folder holds that guide, so anyone can read the source the engine is checked against.

[עברית בהמשך הדף](#hebrew)

| File | What it is |
|---|---|
| [`The-American-Playbook-V2.docx`](The-American-Playbook-V2.docx) | The original, as its authors wrote it. Version 2, last updated 23 September 2026 |
| [`the-american-playbook-v2.md`](the-american-playbook-v2.md) | A reading copy for GitHub, generated from the Word file. Never edited by hand |

The guide is written in Hebrew. Its scripts and templates are in English, because that is the language they are used in.

## From guide to engine

Each module of the guide became data that the engine runs on. Nothing is left as prose for a model to interpret.

| Guide module | Rule table | Engine command |
|---|---|---|
| 1. The Sugar-Coated No: the decoder table, the iron rule, the traffic light, permission to say no | `decoder.json`, `signals.json` | `decode` |
| 2. Extracting feedback: compliment calibration, the question bank, the Mom Test | `decoder.json`, `meetings.json` | `decode`, `prep`, `guard`, `debrief` |
| 3. Email norms: the rules, softeners, the template, the forwardable email | `email.json`, `templates.json` | `lint`, `template` |
| 4. Follow-up: the cadence, the three templates, do and do not, timing | `cadence.json`, `templates.json`, `email.json` | `cadence`, `send-time`, `lint`, `template` |
| 5. Meetings and small talk: the frame, the hard stop, turn-taking, what never to do | `meetings.json` | `prep`, `guard`, `scene`, `debrief` |
| 6. Politics: the three scenarios, the scripts, the quick decoder | `decoder.json`, `meetings.json` | `decode`, `prep`, `scene --politics`, `debrief` |
| 7. The intro economy | `intro.json`, `templates.json` | `intro`, `template` |
| 8. Rapid-fire rules, and geography | `meetings.json`, `decoder.json` | `prep`, `decode` |
| The "Americanize My Email" prompt | `templates.json` | `lint` does the same job in code |

The guide closes with advice to program managers: a simulation workshop and a monthly review of the pipeline against the traffic light. `scene` with `debrief`, and `decode`, are those two in software.

Two things in the engine are not in the guide, and say so. Wherever the guide is qualitative and code needed a number, the choice is tagged `extension` in the data and listed in [ASSUMPTIONS.md](../ASSUMPTIONS.md). And the questions the skill asks a founder before it judges are the skill's own: the guide teaches what to ask an American, the question bank in `interview.json` asks the founder.

## Kept in step, by a check

The guide says of itself that the written guide and the copilot are updated together, version against version. Here that is a build step:

```bash
python3 tools/guide.py
```

It fails when:

- the Word file changed and `data/coach.json` still names the old version,
- the reading copy no longer matches the Word file,
- the guide quotes an English line, or gives a template line, that no rule table has.

That last check is how this version found its own gap. The tables were built from version 1.1.0 of the skill, and the first run against V2 of the guide reported 30 quoted lines the engine did not know: all of module 6 on politics, the frame and the hard stop from module 5, and a few lines from modules 3, 4 and 8. They are in now.

When a new version of the guide arrives:

1. Replace the Word file.
2. Run `python3 tools/guide.py`. It lists what the tables lack.
3. Add the missing rules to the tables, each with a test.
4. Update the version and the hash under `guide` in `data/coach.json`.
5. Run `python3 tools/guide.py --write`, then `python3 tools/build.py`.

## Terms

The guide is © 2026 Nimrod Zemel and Dan Launchpad. All rights reserved.

The Apache-2.0 license of this repository covers the software and the rule tables. It does not cover the two guide files in this folder. Read them, and link to them. To reuse the guide itself, ask the authors.

---

<a id="hebrew"></a>

<div dir="rtl">

## עברית

הסקיל לא ממציא את החוקים שלו. הם באים מ-**The American Playbook**, המדריך שנמרוד זמל כתב יחד עם Dan Launchpad ליזמי התוכנית. התיקייה הזו מחזיקה את המדריך, כדי שכל אחד יוכל לקרוא את המקור שמולו המנוע נבדק.

- **קובץ ה-Word** הוא המקור, כפי שנכתב. גרסה 2, עדכון אחרון 23.9.2026.
- **קובץ ה-Markdown** הוא עותק קריאה שנוצר אוטומטית מקובץ ה-Word. לא עורכים אותו ביד.

### מהמדריך למנוע

כל מודול במדריך הפך לנתונים שהמנוע מריץ. הטבלה למעלה מראה לכל מודול באיזו טבלת חוקים הוא יושב ואיזו פקודה מפעילה אותו. שני דברים במנוע אינם מהמדריך, והם מסומנים כך: מספרים שהקוד היה צריך במקום שבו המדריך איכותי (רשומים ב-[ASSUMPTIONS.md](../ASSUMPTIONS.md)), ובנק השאלות שהסקיל שואל את היזם לפני שהוא שופט.

### נשמרים מסונכרנים, בבדיקה

המדריך אומר על עצמו שהמדריך הכתוב והקופיילוט מתעדכנים יחד, גרסה מול גרסה. כאן זה שלב בבנייה. הבדיקה נכשלת כשקובץ ה-Word השתנה והטבלאות עדיין מצהירות על הגרסה הקודמת, כשעותק הקריאה לא תואם, או כשהמדריך מצטט שורה באנגלית שאין באף טבלת חוקים.

כך הגרסה הזו מצאה את הפער של עצמה: הטבלאות נבנו מגרסה 1.1.0 של הסקיל, והריצה הראשונה מול V2 של המדריך דיווחה על 30 שורות שהמנוע לא הכיר. כל מודול 6 על פוליטיקה, המסגרת וה-hard stop ממודול 5, וכמה שורות ממודולים 3, 4 ו-8. עכשיו הן בפנים.

### תנאים

המדריך הוא © 2026 נמרוד זמל ו-Dan Launchpad. כל הזכויות שמורות. רישיון Apache-2.0 של הריפו חל על התוכנה ועל טבלאות החוקים, ולא על שני קובצי המדריך שבתיקייה הזו. אפשר לקרוא ולקשר. לשימוש חוזר במדריך עצמו פונים למחברים.

</div>
