#!/usr/bin/env python3
"""Draw the README images: the header, one strip per mode, and the social preview.

    python3 tools/make_assets.py

Writes the SVG sources to assets/src/ and, when `rsvg-convert` is installed,
renders them to PNG in assets/. The README shows the PNG files, so they look
the same on every machine. The drawings are original to this repository and
are made of plain shapes and text, nothing traced or imported.

Needs, for the PNG step only: `rsvg-convert` (librsvg) and the Inter typeface
(SIL Open Font License 1.1) installed on the machine. Neither is shipped here.
Nothing in the skill, the engine or the tests depends on this script.
"""

import os
import shutil
import subprocess
import sys

import _paths

OUT = os.path.join(_paths.REPO, "assets")
SRC = os.path.join(OUT, "src")

RED, AMBER, GREEN = "#E5534B", "#F2B134", "#3FB27F"

DARK = {
    "name": "dark",
    "bg1": "#0E1830", "bg2": "#18284D",
    "ink": "#F7F4EC", "muted": "#93A3C4",
    "card": "#F7F4EC", "card_opacity": "0.06", "stroke_opacity": "0.55",
}
LIGHT = {
    "name": "light",
    "bg1": "#F7F4EC", "bg2": "#EFEADD",
    "ink": "#14213D", "muted": "#5C6B8A",
    "card": "#FFFFFF", "card_opacity": "0.9", "stroke_opacity": "0.55",
}

FONT = "Inter, 'Inter Display', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
DISPLAY = "'Inter Display', Inter, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO = "'DejaVu Sans Mono', Menlo, Consolas, monospace"


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_open(width, height, p):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">\n'
        "<defs>\n"
        '  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">\n'
        '    <stop offset="0" stop-color="{bg1}"/><stop offset="1" stop-color="{bg2}"/>\n'
        "  </linearGradient>\n"
        '  <marker id="arrow" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="9" markerHeight="9" orient="auto-start-reverse">\n'
        '    <path d="M1 1 L11 6 L1 11" fill="none" stroke="{ink}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>\n'
        "  </marker>\n"
        "</defs>\n"
        '<rect width="{w}" height="{h}" fill="url(#bg)"/>\n'
    ).format(w=width, h=height, bg1=p["bg1"], bg2=p["bg2"], ink=p["ink"])


def text(x, y, content, p, size=24, weight=400, fill=None, opacity=1.0, anchor="start", family=FONT, spacing=0):
    return (
        '<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        'fill-opacity="{opacity}" text-anchor="{anchor}" letter-spacing="{spacing}">{content}</text>\n'
    ).format(x=x, y=y, family=family, size=size, weight=weight, fill=fill or p["ink"], opacity=opacity,
             anchor=anchor, spacing=spacing, content=esc(content))


def card(x, y, w, h, p, radius=18):
    return (
        '<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{card}" fill-opacity="{co}" '
        'stroke="{ink}" stroke-opacity="{so}" stroke-width="2"/>\n'
    ).format(x=x, y=y, w=w, h=h, r=radius, card=p["card"], co=p["card_opacity"], ink=p["ink"], so=p["stroke_opacity"])


def bubble(x, y, w, h, p, tail="left", radius=22):
    """A speech bubble drawn as one outline: a rounded card with a tail under one corner."""
    r = radius
    if tail == "left":
        near, tip, far = x + 66, x + 30, x + 38
    else:
        near, tip, far = x + w - 38, x + w - 30, x + w - 66
    d = (
        "M{x1} {y} H{x2} A{r} {r} 0 0 1 {xr} {y1} V{y2} A{r} {r} 0 0 1 {x2} {yb} "
        "H{near} L{tip} {yt} L{far} {yb} H{x1} A{r} {r} 0 0 1 {x} {y2} V{y1} A{r} {r} 0 0 1 {x1} {y} Z"
    ).format(x=x, y=y, r=r, x1=x + r, x2=x + w - r, xr=x + w, y1=y + r, y2=y + h - r, yb=y + h, yt=y + h + 26,
             near=near, tip=tip, far=far)
    return (
        '<path d="{d}" fill="{card}" fill-opacity="{co}" stroke="{ink}" stroke-opacity="{so}" stroke-width="2" '
        'stroke-linejoin="round"/>\n'
    ).format(d=d, card=p["card"], co=p["card_opacity"], ink=p["ink"], so=p["stroke_opacity"])


def bar(x, y, w, p, opacity=0.38, height=10):
    return '<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{ink}" fill-opacity="{o}"/>\n'.format(
        x=x, y=y, w=w, h=height, ink=p["ink"], o=opacity)


def dot(cx, cy, r, color, opacity=1.0):
    return '<circle cx="{cx}" cy="{cy}" r="{r}" fill="{c}" fill-opacity="{o}"/>\n'.format(cx=cx, cy=cy, r=r, c=color, o=opacity)


def ask(cx, cy, color, p):
    """A small round question mark: one ask."""
    return dot(cx, cy, 15, color) + text(cx, cy + 7, "?", p, size=20, weight=800, fill="#FFFFFF", anchor="middle")


def arrow(x1, y1, x2, y2, p, dashed=False):
    dash = ' stroke-dasharray="3 9"' if dashed else ""
    return (
        '<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{ink}" stroke-opacity="0.8" stroke-width="2.5" '
        'stroke-linecap="round"{dash} marker-end="url(#arrow)"/>\n'
    ).format(x1=x1, y1=y1, x2=x2, y2=y2, ink=p["ink"], dash=dash)


def tick(cx, cy, p):
    return dot(cx, cy, 15, GREEN) + (
        '<path d="M{a} {b} l5 6 l10 -12" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
    ).format(a=cx - 7, b=cy + 1)


def cross(cx, cy, p):
    return dot(cx, cy, 15, RED) + (
        '<path d="M{a} {b} l10 10 M{c} {b} l-10 10" fill="none" stroke="#FFFFFF" stroke-width="3.2" stroke-linecap="round"/>\n'
    ).format(a=cx - 5, b=cy - 5, c=cx + 5)


# --------------------------------------------------------------------- header

def cover(w, h, left, right, big, scale):
    """The name, the promise, and three things an American says with what each is worth."""
    p = DARK
    out = [svg_open(w, h, p)]
    size = lambda value: int(round(value * scale))
    # left: the mark, the name, the promise
    for index, color in enumerate((RED, AMBER, GREEN)):
        out.append(dot(left + size(12) + index * size(34), 150, size(11), color))
    out.append(text(left, 210, "A SKILL FOR ISRAELI FOUNDERS", p, size=size(21), weight=600, fill=p["muted"], spacing=3))
    out.append(text(left - 4, 210 + size(108), "The American", p, size=big, weight=800, family=DISPLAY, spacing=-3))
    out.append(text(left - 4, 210 + size(108) + big + 2, "Playbook", p, size=big, weight=800, family=DISPLAY, spacing=-3))
    base = 210 + size(108) + big + 2
    out.append(text(left, base + size(68), "Hear the no behind the nice.", p, size=size(34), weight=500, opacity=0.92))
    out.append(text(left, base + size(116), "The model interviews and writes. Code judges.", p, size=size(22), fill=p["muted"]))
    # right: three things an American says, and what each one is worth
    rows = [
        ("\u201cThis is amazing!\u201d", AMBER, "manners, not data", 330),
        ("\u201cLet\u2019s keep in touch.\u201d", RED, "a soft no", 392),
        ("\u201cWhat would pricing look like?\u201d", GREEN, "real interest", 520),
    ]
    y = 96
    for quote, color, meaning, width in rows:
        x = right
        out.append(bubble(x, y, size(width), 70, p))
        out.append(text(x + 30, y + 45, quote, p, size=size(27), weight=500))
        out.append(
            '<path d="M{a} {b} v26 h30" fill="none" stroke="{ink}" stroke-opacity="0.55" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" marker-end="url(#arrow)"/>\n'.format(a=x + 96, b=y + 82, ink=p["ink"])
        )
        out.append(dot(x + 152, y + 108, 10, color))
        out.append(text(x + 174, y + 116, meaning, p, size=size(23), weight=600, opacity=0.95))
        y += 164
    out.append("</svg>\n")
    return "".join(out)


def header():
    """The banner at the top of the README, 1600 by 640."""
    return cover(1600, 640, left=96, right=960, big=104, scale=1.0)


def social_preview():
    """The same cover at 1280 by 640, the size GitHub asks for a social preview."""
    return cover(1280, 640, left=72, right=748, big=88, scale=0.86)


# ---------------------------------------------------------------------- strips

def interview_strip(p):
    w, h = 1600, 400
    out = [svg_open(w, h, p)]
    # the first telling: a mood, not a fact
    out.append(bubble(96, 96, 440, 150, p))
    out.append(text(130, 156, "“Great meeting.", p, size=30, weight=600))
    out.append(text(130, 204, "I think it’s closed.”", p, size=30, weight=600))
    out.append(text(316, 322, "what you said", p, size=20, fill=p["muted"], anchor="middle"))
    out.append(arrow(576, 190, 646, 190, p))
    # three questions a turn, the musts first, each with its reason
    out.append(card(682, 44, 500, 280, p))
    questions = [
        ("Who is the American here?", "it decides the framework"),
        ("What did they say, word for word?", "a summary hides the words that matter"),
        ("Is there an agreed next step?", "no step means no deal"),
    ]
    for index, (label, why) in enumerate(questions):
        y = 96 + index * 84
        out.append(ask(728, y, AMBER, p))
        out.append(text(764, y + 4, label, p, size=23, weight=600))
        out.append(text(764, y + 32, why, p, size=18, fill=p["muted"]))
    out.append(text(932, 362, "three questions a turn, each with its reason", p, size=20, fill=p["muted"], anchor="middle"))
    out.append(arrow(1218, 190, 1288, 190, p))
    # the picture so far: what is known in each dimension
    out.append(text(1408, 96, "37%", p, size=60, weight=800, anchor="middle", family=DISPLAY))
    rows = [("who", 1, 2), ("said", 1, 5), ("cost", 1, 2), ("next", 1, 2), ("goal", 0, 1)]
    for index, (label, known, of) in enumerate(rows):
        y = 136 + index * 36
        out.append(text(1366, y + 11, label, p, size=18, fill=p["muted"], anchor="end"))
        out.append('<rect x="1380" y="{y}" width="130" height="12" rx="6" fill="{ink}" fill-opacity="0.16"/>\n'.format(y=y, ink=p["ink"]))
        if known:
            out.append('<rect x="1380" y="{y}" width="{w}" height="12" rx="6" fill="{c}"/>\n'.format(y=y, w=int(130 * known / float(of)), c=GREEN))
    out.append(text(1408, 362, "the picture so far", p, size=20, fill=p["muted"], anchor="middle"))
    out.append("</svg>\n")
    return "".join(out)


def email_strip(p):
    w, h = 1600, 400
    out = [svg_open(w, h, p)]
    # before: long, formal, three asks
    out.append(card(110, 44, 430, 300, p))
    out.append(text(140, 90, "Dear Sir or Madam,", p, size=22, weight=500, opacity=0.9))
    widths = [360, 330, 350, 300, 340, 250, 345, 220, 310]
    for index, width in enumerate(widths):
        out.append(bar(140, 112 + index * 23, width, p, opacity=0.26))
    for index in (5, 7, 8):
        out.append(ask(140 + widths[index] + 28, 117 + index * 23, RED, p))
    out.append(text(325, 378, "9 sentences, 3 asks", p, size=20, fill=p["muted"], anchor="middle"))
    # the check in between
    out.append(arrow(580, 194, 700, 194, p))
    out.append(text(640, 172, "lint", p, size=20, weight=600, anchor="middle", family=MONO, opacity=0.9))
    # after: short, first name, one closed ask
    out.append(card(740, 84, 430, 220, p))
    out.append(text(770, 130, "Hi Michael,", p, size=22, weight=500, opacity=0.9))
    for index, width in enumerate((350, 300, 240)):
        out.append(bar(770, 156 + index * 26, width, p, opacity=0.5))
    out.append(ask(770 + 240 + 30, 213, GREEN, p))
    out.append(text(770, 270, "Best, Dana", p, size=20, opacity=0.7))
    out.append(text(955, 338, "3 sentences, 1 ask", p, size=20, fill=p["muted"], anchor="middle"))
    # when to send, on both clocks
    out.append(arrow(1208, 194, 1290, 194, p, dashed=True))
    out.append(card(1318, 124, 190, 140, p, radius=16))
    out.append(text(1413, 172, "Tue 09:30 ET", p, size=22, weight=700, anchor="middle"))
    out.append(text(1413, 206, "16:30 Israel", p, size=20, anchor="middle", opacity=0.85))
    out.append(text(1413, 240, "not a holiday", p, size=17, fill=p["muted"], anchor="middle"))
    out.append("</svg>\n")
    return "".join(out)


def decoder_strip(p):
    w, h = 1600, 400
    out = [svg_open(w, h, p)]
    # what was said
    out.append(bubble(96, 96, 500, 150, p))
    out.append(text(130, 156, "“This is amazing!", p, size=30, weight=600))
    out.append(text(130, 204, "Let’s keep in touch.”", p, size=30, weight=600))
    out.append(text(346, 322, "what they said", p, size=20, fill=p["muted"], anchor="middle"))
    out.append(arrow(636, 190, 716, 190, p))
    # the three facts the engine asks for
    out.append(card(752, 60, 430, 250, p))
    facts = [("their exact words", True), ("a dated next step", False), ("something it cost them", False)]
    for index, (label, have) in enumerate(facts):
        y = 118 + index * 68
        out.append(tick(800, y, p) if have else cross(800, y, p))
        out.append(text(836, y + 8, label, p, size=24, weight=500))
    out.append(text(967, 352, "what the engine checks", p, size=20, fill=p["muted"], anchor="middle"))
    out.append(arrow(1218, 190, 1298, 190, p))
    # the verdict
    out.append(
        '<rect x="1336" y="40" width="112" height="280" rx="26" fill="{ink}" fill-opacity="0.08" stroke="{ink}" '
        'stroke-opacity="0.6" stroke-width="2"/>\n'.format(ink=p["ink"])
    )
    out.append(dot(1392, 96, 30, RED, 0.5))
    out.append(dot(1392, 180, 30, AMBER, 1.0))
    out.append(dot(1392, 264, 30, GREEN, 0.14))
    out.append('<circle cx="1392" cy="180" r="38" fill="none" stroke="{c}" stroke-opacity="0.45" stroke-width="3"/>\n'.format(c=AMBER))
    out.append(text(1392, 360, "Yellow, leaning Red", p, size=22, weight=700, anchor="middle"))
    out.append("</svg>\n")
    return "".join(out)


def prep_strip(p):
    w, h = 1600, 400
    out = [svg_open(w, h, p)]
    # the prep sheet
    out.append(card(96, 50, 400, 280, p))
    out.append(text(126, 96, "Prep sheet: investor", p, size=23, weight=700))
    rows = [("goal: a second partner meeting", 0), ("the ask, in one line", 0), ("soft-nos to expect", 0)]
    for index, (label, _unused) in enumerate(rows):
        y = 142 + index * 44
        out.append('<rect x="126" y="{y}" width="14" height="14" rx="3" fill="{ink}" fill-opacity="0.55"/>\n'.format(y=y - 12, ink=p["ink"]))
        out.append(text(154, y, label, p, size=20, opacity=0.9))
    out.append(
        '<rect x="126" y="268" width="150" height="38" rx="19" fill="{c}" fill-opacity="0.16" stroke="{c}" stroke-width="2"/>\n'.format(c=RED)
    )
    out.append(text(201, 294, "BANT: off", p, size=19, weight=700, anchor="middle"))
    out.append(text(296, 368, "prepare", p, size=20, fill=p["muted"], anchor="middle"))
    out.append(arrow(532, 190, 602, 190, p))
    # the rehearsal: the American never says no, the founder asks for a date
    out.append(bubble(640, 52, 380, 74, p, tail="left"))
    out.append(text(668, 98, "“We’ll circle back.”", p, size=25, weight=500))
    out.append(text(1034, 98, "Michael", p, size=18, fill=p["muted"]))
    out.append(bubble(700, 196, 440, 74, p, tail="right"))
    out.append(text(728, 242, "“Would Thursday at 10 work?”", p, size=25, weight=500))
    out.append(text(686, 242, "you", p, size=18, fill=p["muted"], anchor="end"))
    out.append(text(890, 368, "rehearse, in English", p, size=20, fill=p["muted"], anchor="middle"))
    out.append(arrow(1180, 190, 1250, 190, p))
    # the score
    out.append('<circle cx="1392" cy="182" r="96" fill="none" stroke="{ink}" stroke-opacity="0.18" stroke-width="16"/>\n'.format(ink=p["ink"]))
    out.append(
        '<circle cx="1392" cy="182" r="96" fill="none" stroke="{c}" stroke-width="16" stroke-linecap="round" '
        'stroke-dasharray="519 603" transform="rotate(-90 1392 182)"/>\n'.format(c=GREEN)
    )
    out.append(text(1392, 204, "8.6", p, size=64, weight=800, anchor="middle", family=DISPLAY))
    out.append(text(1392, 238, "out of 10", p, size=18, fill=p["muted"], anchor="middle"))
    out.append(text(1392, 368, "scored by code", p, size=20, fill=p["muted"], anchor="middle"))
    out.append("</svg>\n")
    return "".join(out)


def drawings():
    files = [("header", header()), ("social-preview", social_preview())]
    for name, maker in (("the-interview", interview_strip), ("email-doctor", email_strip), ("meeting-decoder", decoder_strip), ("prep-and-simulation", prep_strip)):
        files.append((name, maker(DARK)))
        files.append((name + "-light", maker(LIGHT)))
    return files


def main():
    os.makedirs(SRC, exist_ok=True)
    renderer = shutil.which("rsvg-convert")
    for name, svg in drawings():
        source = os.path.join(SRC, name + ".svg")
        with open(source, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(svg)
        if renderer:
            subprocess.run([renderer, "--format", "png", "--output", os.path.join(OUT, name + ".png"), source], check=True)
    print("%d drawings written to assets/src/%s" % (len(drawings()), "" if renderer else " (rsvg-convert not found: no PNG files rendered)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
