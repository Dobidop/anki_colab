#!/usr/bin/env python3
"""Build the shared Anki pack (`.apkg`) from the markdown card files.

The markdown in `<kurskod>/*.md` is the source of truth. This script reads it
and writes one `.apkg` that anyone can import into Anki. Re-importing a newer
pack updates the cards in place and keeps everyone's review history, because
each card carries a stable id:

    ### Vad är formativ bedömning?
    <!-- anki: 90601bdb -->
    > källa: McMillan (2018), s. 515 · lärandemål: …

    **Svar:** Bedömning under lärandet, för att …

A card is a `###` question, an optional `> källa: …` block, and everything
under `**Svar:**` until the next heading or `---`. **Only cards with a written
Svar go into the pack.** A front with a blank back stays in the repo as an open
question that someone can answer.

The `<!-- anki: … -->` line is added by `--assign-ids` (the GitHub Action runs
it after every merge). Never copy it along when duplicating a card, and never
change it: a new id makes the card a new card for everyone.

Frontmatter of a card file:

    course: 972G03            # deck LiU::972G03
    type: cards
    deck: Begreppslista       # optional sub-deck, nest with ::
    reverse: true             # also ask definition → term (term cards only)
    references:               # full APA 7 references, shown on every card
      - "McMillan, J. H. (2018). *Classroom assessment* … Pearson."

`reverse: true` adds a reversed card to every plain "Vad är X?" / "Vad menas
med X?" card, in the sub-decks `…::Framåt` and `…::Omvänt`. Words of the
definition that would give the term away are blanked on the reversed front.

Usage:
    python tools/build.py                      # validate and build dist/liu-kort.apkg
    python tools/build.py --check              # validate and report only
    python tools/build.py --assign-ids         # give answered cards without an id one
    python tools/build.py --repo owner/name    # link each card to its file on GitHub
"""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import secrets
import sys
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COURSE_DIR_RE = re.compile(r"^\d{3}G\d{2}$")

MODEL = "LiU-kort (delad)"
MODEL_ID = 1730412961          # fixed forever: a new id would duplicate every card
FIELDS = ["Fråga", "Svar", "Källa", "Referens", "Id", "Fil", "Omvänt"]
DECK_ROOT = "LiU"
GUID_NS = "liu-kort"
SKIP_TAGS = {"cards", "srs"}
UNCHECKED = "⚠"
UNCHECKED_TAG = "okontrollerad"

CSS = """\
.card { font-family: system-ui, sans-serif; font-size: 19px; line-height: 1.45;
        text-align: left; max-width: 42em; margin: 0 auto; padding: 0 12px; }
.q { font-weight: 600; }
.svar { margin-top: .5em; }
.kalla { margin-top: 1.4em; font-size: 14px; opacity: .65; }
.ref { margin-top: .4em; font-size: 13px; opacity: .55; }
.ref div { padding-left: 1.5em; text-indent: -1.5em; }
.fil { margin-top: .3em; font-size: 12px; opacity: .45; }
code { font-size: .92em; }
blockquote { margin: .5em 0; padding-left: .8em; border-left: 3px solid #999; }
.omv .eng { display: none; }
.omv .lk { color: transparent; border-bottom: 1px solid #999; }
"""
TAIL = ('<div class="kalla">{{Källa}}</div>'
        '{{#Referens}}<div class="ref">{{Referens}}</div>{{/Referens}}'
        '<div class="fil">{{Fil}}</div>')
FRONT = '<div class="q">{{Fråga}}</div>'
BACK = '<div class="q">{{Fråga}}</div><hr id="answer"><div class="svar">{{Svar}}</div>' + TAIL
# The reversed card exists only where Omvänt is filled in: Anki skips a card
# whose front renders empty.
FRONT_R = ('{{#Omvänt}}<div class="q">Vilket begrepp?</div>'
           '<div class="svar omv">{{Svar}}</div>{{/Omvänt}}')
BACK_R = ('<div class="q">Vilket begrepp?</div><div class="svar">{{Svar}}</div>'
          '<hr id="answer"><div class="q">{{Omvänt}}</div>' + TAIL)
TEMPLATES = [("Kort", FRONT, BACK), ("Omvänt", FRONT_R, BACK_R)]
FORWARD_DECK, REVERSE_DECK = "Framåt", "Omvänt"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
ID_RE = re.compile(r"^\s*<!--\s*anki:\s*([0-9a-f]+)\s*-->\s*$")
SVAR_RE = re.compile(r"^\s*\*\*Svar:?\*\*:?\s*(.*)$")
RULE_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
TERM_RE = re.compile(r"^Vad (?:är|menas med) (?!skillnaden )(?:en |ett |den |det )?([^?]+)\?$")
ENG_RE = re.compile(r"^\s*\*\([^)]*\)\*\s*")
# a term word found in this many terms of one file is generic, not a giveaway
COMMON_TERMS = 3
LINK_WORDS = {"eller", "samt", "inom", "från", "mellan", "under", "efter", "inför", "över"}
# a preposition makes the first word the head ("bias i bedömning"), so no head is exempt
LINKING = {"i", "för", "som", "hos", "av", "om", "på", "med", "till", "vid"} | LINK_WORDS


# ---------------------------------------------------------------- parsing

@dataclass
class Card:
    path: Path
    line: int              # index of the ### line
    question: str
    card_id: str | None
    kalla: list[str]
    answer: list[str]
    course: str
    tags: list[str]
    references: list[str]
    subdeck: str = ""
    reverse: bool = False      # the file asks for reversed cards
    common: frozenset[str] = frozenset()   # term words shared by many terms in the file

    @property
    def rel(self) -> str:
        return self.path.relative_to(ROOT).as_posix()

    @property
    def deck(self) -> str:
        return "::".join(p for p in (DECK_ROOT, self.course, self.subdeck) if p)

    def deck_for(self, ord_: int) -> str:
        """Deck of the card made by template `ord_` (0 forward, 1 reversed)."""
        if not self.reverse:
            return self.deck
        return f"{self.deck}::{REVERSE_DECK if ord_ else FORWARD_DECK}"

    @property
    def term(self) -> str:
        m = TERM_RE.match(self.question.strip())
        # a comma outside parentheses means the question goes on after the term
        if not m or "," in re.sub(r"\([^)]*\)", "", m.group(1)):
            return ""
        return m.group(1).strip()

    @property
    def core(self) -> str:
        """The term without its parenthesised gloss or emphasis, lowercased."""
        return re.sub(r"\([^)]*\)", "", self.term).replace("*", "").strip().lower()

    @property
    def term_words(self) -> list[str]:
        return [w for w in re.split(r"[\s\-–/]+", self.core)
                if len(w) >= 4 and w not in LINK_WORDS]

    @property
    def head_words(self) -> set[str]:
        """The category noun of a modifier + noun term: the *prov* of high-stakes-prov.
        Seeing it says what kind of thing the term is, not which one, so it stays."""
        heads = set()
        for part in re.split(r"\s+(?:och|eller)\s+", self.core):
            words = [w for w in re.split(r"[\s\-–/]+", part) if w]
            if len(words) >= 2 and not any(w in LINKING for w in words):
                heads.add(words[-1])
        return heads

    @property
    def clue_re(self) -> re.Pattern | None:
        """Words of the definition that would give the term away on the reversed front."""
        words = [w for w in self.term_words
                 if w not in self.common and w not in self.head_words]
        if not words:
            return None
        return re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\w*", re.I)

    @property
    def why_not_reversed(self) -> str:
        """Empty when the card gets a reversed twin, else the reason."""
        if not self.reverse:
            return "file has no reverse: true"
        if not self.term:
            return "not a plain term question"
        core = self.core
        body = ENG_RE.sub("", " ".join(self.answer), count=1).replace("*", "").lower()
        if core and re.search(rf"\b{re.escape(core)}\b", body):
            return "definition contains the term"
        return ""

    @property
    def reversed(self) -> bool:
        return not self.why_not_reversed

    @property
    def has_answer(self) -> bool:
        return any(l.strip() for l in self.answer)

    @property
    def unchecked(self) -> bool:
        return any(UNCHECKED in t for t in self.kalla + self.answer)

    @property
    def all_tags(self) -> list[str]:
        return self.tags + ([UNCHECKED_TAG] if self.unchecked else [])

    def fields(self, repo: str = "") -> list[str]:
        svar = blocks(self.answer)
        if self.reversed:
            # wrap the opening "(english term)" so the reversed front can hide it
            svar = re.sub(r"^<div><i>(\([^)]*\))</i>",
                          r'<div><span class="eng"><i>\1</i></span>', svar)
            if (rx := self.clue_re):
                # text between tags only, so no tag or attribute is touched, and
                # not inside the English gloss, which is hidden already
                head, sep, rest = svar.partition("</i></span>")
                if not sep:
                    head, rest = "", svar
                rest = re.sub(r"(?<=>)[^<]+|^[^<]+",
                              lambda t: rx.sub(r'<span class="lk">\g<0></span>', t.group(0)),
                              rest)
                svar = head + sep + rest
        return [
            inline(self.question),
            svar,
            inline(" ".join(self.kalla)),
            "".join(f"<div>{inline(r)}</div>" for r in self.references),
            self.card_id or "",
            self.file_field(repo),
            inline(self.term) if self.reversed else "",
        ]

    def file_field(self, repo: str) -> str:
        label = html.escape(f"{self.rel} · {self.card_id}")
        if not repo:
            return label
        url = f"https://github.com/{repo}"
        issue = urllib.parse.urlencode({
            "template": "fel-i-kort.yml",
            "title": f"Fel i kort: {self.question[:60]}",
            "kort": f"{self.card_id} · {self.rel}",
        })
        return (f'<a href="{url}/blob/main/{urllib.parse.quote(self.rel)}">{label}</a>'
                f' · <a href="{url}/issues/new?{html.escape(issue)}">rapportera fel</a>')


def frontmatter(lines: list[str]) -> tuple[dict[str, str | list[str]], int]:
    """Flat `key: value` pairs, plus `key:` followed by `  - item` lists."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta: dict[str, str | list[str]] = {}
    key = ""
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, i + 1
        if (item := re.match(r"^\s+-\s+(.*)$", line)) and key:
            prev = meta.get(key)
            meta[key] = (prev if isinstance(prev, list) else []) + [unquote(item.group(1))]
            continue
        k, sep, v = line.partition(":")
        if sep:
            key = k.strip()
            meta[key] = v.strip()
    return {}, 0


def unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1]
    return s


def as_str(v: str | list[str] | None) -> str:
    return unquote(v) if isinstance(v, str) else ""


def parse_tags(raw: str) -> list[str]:
    raw = raw.strip().strip("[]")
    return [t.strip().strip("'\"") for t in raw.split(",") if t.strip()]


def parse_file(path: Path) -> list[Card]:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta, start = frontmatter(lines)
    if as_str(meta.get("type")) != "cards":
        return []
    course = as_str(meta.get("course")) or path.parent.name
    tags = [course, path.stem] + [t for t in parse_tags(as_str(meta.get("tags")))
                                  if t not in SKIP_TAGS]
    tags = [re.sub(r"\s+", "_", t) for t in tags]
    refs = meta.get("references")
    references = refs if isinstance(refs, list) else []
    subdeck = "::".join(p.strip() for p in as_str(meta.get("deck")).split("::") if p.strip())
    reverse = as_str(meta.get("reverse")).lower() in ("true", "yes", "ja")

    # blank out fenced code blocks, so a format example isn't a card
    fenced = False
    for j in range(start, len(lines)):
        if FENCE_RE.match(lines[j]):
            fenced = not fenced
            lines[j] = ""
        elif fenced:
            lines[j] = ""

    cards: list[Card] = []
    i = start
    while i < len(lines):
        m = HEADING_RE.match(lines[i])
        if not (m and len(m.group(1)) == 3):
            i += 1
            continue
        card = Card(path, i, m.group(2), None, [], [], course, tags, references, subdeck, reverse)
        i += 1
        in_answer = False
        while i < len(lines):
            line = lines[i]
            if HEADING_RE.match(line) or RULE_RE.match(line):
                break
            if not in_answer:
                if (idm := ID_RE.match(line)):
                    card.card_id = idm.group(1)
                elif (sm := SVAR_RE.match(line)):
                    in_answer = True
                    if sm.group(1):
                        card.answer.append(sm.group(1))
                elif line.startswith(">"):
                    card.kalla.append(re.sub(r"^>\s*(källa:\s*)?", "", line, flags=re.I))
            else:
                card.answer.append(line)
            i += 1
        # no **Svar:** marker means no answer, so has_answer keeps it out
        cards.append(card)
    if reverse:
        seen = Counter(w for c in cards for w in set(c.term_words))
        common = frozenset(w for w, n in seen.items() if n >= COMMON_TERMS)
        for c in cards:
            c.common = common
    return cards


def card_files() -> list[Path]:
    return sorted(p for d in ROOT.iterdir() if d.is_dir() and COURSE_DIR_RE.match(d.name)
                  for p in d.glob("*.md"))


def all_cards() -> list[Card]:
    return [c for p in card_files() for c in parse_file(p)]


# ------------------------------------------------- markdown → Anki HTML

def inline(text: str) -> str:
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"==(.+?)==", r"<mark>\1</mark>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)$")


def blocks(lines: list[str]) -> str:
    """Just enough markdown for an answer: paragraphs, lists, quotes."""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    ordered = False
    quote: list[str] = []

    def flush() -> None:
        nonlocal para, items, quote
        if para:
            out.append("<div>" + "<br>".join(inline(l.strip()) for l in para) + "</div>")
        if items:
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
        if quote:
            out.append("<blockquote>" + "<br>".join(inline(l) for l in quote) + "</blockquote>")
        para, items, quote = [], [], []

    for line in lines:
        if not line.strip():
            flush()
        elif (lm := LIST_RE.match(line)):
            if para or quote:
                flush()
            if not items:
                ordered = lm.group(1)[0].isdigit()
            items.append(lm.group(2))
        elif line.lstrip().startswith(">"):
            if para or items:
                flush()
            quote.append(re.sub(r"^\s*>\s?", "", line))
        elif items and line.startswith(("  ", "\t")):
            items[-1] += " " + line.strip()
        else:
            if items or quote:
                flush()
            para.append(line)
    flush()
    return "".join(out)


# ---------------------------------------------------------------- ids

def write_ids(new: list[Card]) -> None:
    by_file: dict[Path, list[Card]] = {}
    for c in new:
        by_file.setdefault(c.path, []).append(c)
    for path, cards in by_file.items():
        raw = path.read_bytes().decode("utf-8")
        nl = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.split(nl)
        for c in sorted(cards, key=lambda c: c.line, reverse=True):
            lines.insert(c.line + 1, f"<!-- anki: {c.card_id} -->")
        path.write_bytes(nl.join(lines).encode("utf-8"))


# ---------------------------------------------------------------- package

def deck_id(name: str) -> int:
    """Stable per deck name, so a re-import lands in the same deck."""
    return int(hashlib.sha1(name.encode()).hexdigest()[:8], 16) | (1 << 31)


def build(ready: list[Card], out: Path, repo: str) -> None:
    import genanki   # only the build needs it; --check and --assign-ids run on bare Python

    class DeckCard(genanki.Card):
        """A card that goes to its own deck: the reversed twin of a term card
        sits in …::Omvänt while its note lives in …::Framåt."""
        def __init__(self, ord_: int, did: int):
            super().__init__(ord_)
            self.did = did

        def write_to_db(self, cursor, timestamp, deck_id, note_id, id_gen, due=0):
            super().write_to_db(cursor, timestamp, self.did, note_id, id_gen, due)

    model = genanki.Model(
        MODEL_ID, MODEL,
        fields=[{"name": f} for f in FIELDS],
        templates=[{"name": n, "qfmt": q, "afmt": a} for n, q, a in TEMPLATES],
        css=CSS, sort_field_index=0)

    decks: dict[str, genanki.Deck] = {}

    def deck(name: str) -> genanki.Deck:
        # parents too, so the tree imports whole even where a level holds no cards
        parts = name.split("::")
        for k in range(1, len(parts) + 1):
            n = "::".join(parts[:k])
            decks.setdefault(n, genanki.Deck(deck_id(n), n))
        return decks[name]

    for c in ready:
        note = genanki.Note(model=model, fields=c.fields(repo), tags=c.all_tags,
                            guid=genanki.guid_for(GUID_NS, c.card_id))
        note.cards[:] = [DeckCard(k.ord, deck(c.deck_for(k.ord)).deck_id) for k in note.cards]
        deck(c.deck_for(0)).add_note(note)

    out.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(list(decks.values())).write_to_file(str(out))


def summary(cards: list[Card], ready: list[Card]) -> str:
    per_deck = Counter(c.deck for c in ready)
    open_q = Counter(c.course for c in cards if not c.has_answer)
    reversed_n = sum(c.reversed for c in ready)
    unchecked = sum(c.unchecked for c in ready)
    rows = "\n".join(f"| {d} | {n} |" for d, n in sorted(per_deck.items()))
    opens = ", ".join(f"{k}: {n}" for k, n in sorted(open_q.items())) or "inga"
    return (f"**{len(ready)} kort** ({reversed_n} med omvänd variant), varav "
            f"{unchecked} märkta ⚠ (taggen `{UNCHECKED_TAG}`).\n\n"
            f"| Lek | Kort |\n|---|---|\n{rows}\n\n"
            f"Frågor som ännu saknar svar, och därför inte är med: {opens}.\n")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate and report; build nothing")
    ap.add_argument("--assign-ids", action="store_true", help="write an id line into answered cards that lack one")
    ap.add_argument("--out", type=Path, default=ROOT / "dist" / "liu-kort.apkg")
    ap.add_argument("--summary", type=Path, help="also write a markdown summary here")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""),
                    help="owner/name on GitHub, for the links on each card")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    errors: list[str] = []
    stray = [p.relative_to(ROOT).as_posix() for p in ROOT.glob("*/*.md")
             if p.parent.name not in {".github", "tools", "dist"}
             and not COURSE_DIR_RE.match(p.parent.name)]
    for s in stray:
        errors.append(f"{s}: card files go in a folder named after the course code, e.g. 972G03/")
    for p in card_files():
        meta, _ = frontmatter(p.read_text(encoding="utf-8").splitlines())
        rel = p.relative_to(ROOT).as_posix()
        if as_str(meta.get("type")) != "cards":
            errors.append(f"{rel}: frontmatter needs type: cards")
        elif as_str(meta.get("course")) not in ("", p.parent.name):
            errors.append(f"{rel}: course: {as_str(meta.get('course'))} but the file is in {p.parent.name}/")
        elif not isinstance(meta.get("references"), list):
            print(f"warning: {rel} has no references: list", file=sys.stderr)

    cards = all_cards()
    ready = [c for c in cards if c.has_answer]

    seen: dict[str, Card] = {}
    for c in ready:
        if c.card_id and c.card_id in seen:
            o = seen[c.card_id]
            errors.append(f"duplicate id {c.card_id}: {o.rel}:{o.line + 1} and {c.rel}:{c.line + 1}. "
                          "Remove the <!-- anki: … --> line from the copy.")
        elif c.card_id:
            seen[c.card_id] = c

    fresh = [c for c in ready if not c.card_id]
    if fresh and args.assign_ids and not errors:
        for c in fresh:
            new_id = secrets.token_hex(4)
            while new_id in seen:
                new_id = secrets.token_hex(4)
            c.card_id = new_id
            seen[new_id] = c
        write_ids(fresh)
        print(f"Wrote {len(fresh)} id line(s).")
        fresh = []

    per_file: dict[str, list[int]] = {}
    for c in cards:
        t = per_file.setdefault(c.rel, [0, 0])
        t[0] += 1
        t[1] += c.has_answer
    print("Kort med svar / alla:")
    for rel, (total, done) in per_file.items():
        print(f"  {done:3d} / {total:3d}  {rel}")
    print(f"  {len(ready):3d} / {len(cards):3d}  totalt\n")
    if fresh:
        print(f"{len(fresh)} answered card(s) without an id yet; they get one on merge "
              "(or run --assign-ids):")
        for c in fresh:
            print(f"  + {c.rel}:{c.line + 1}  {c.question[:70]}")

    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if errors:
        return 1
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(summary(cards, ready), encoding="utf-8")
    if args.check or args.assign_ids:
        return 0
    if fresh:
        print("error: can't build while cards lack an id; run with --assign-ids first", file=sys.stderr)
        return 1
    build(ready, args.out, args.repo)
    print(f"Built {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}: "
          f"{len(ready)} notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
