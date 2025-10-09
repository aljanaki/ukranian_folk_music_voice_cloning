#!/usr/bin/env python3
"""MEI translator: transliterate Cyrillic (Ukrainian) lyrics/syllables to Latin phoneme-like text.

Usage:
  python mei_translator.py input.mei -o output.mei
  python mei_translator.py input.xml --inplace

Behavior:
 - Finds XML elements whose text contains Cyrillic letters and transliterates the text.
 - Stores the original text in an attribute `orig` and the transliteration in `phon`.
 - By default writes to stdout if no output file provided; use -o/--outfile or --inplace.

This is a small, dependency-free utility using stdlib xml.etree. The transliteration is
an approximate, ASCII-friendly mapping for Ukrainian Cyrillic to Latin (phoneme-like).
"""

from __future__ import annotations

import argparse
import re
import sys
from xml.etree import ElementTree as ET
from typing import Dict


CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def build_mappings() -> Dict[str, str]:
    # Base single-letter mappings (lowercase)
    m = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "h",
        "ґ": "g",
        "д": "d",
        "е": "e",
        "ж": "zh",
        "з": "z",
        "и": "y",
        "і": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ь": "'",
        "'": "'",
        "ʼ": "'",
        "’": "'",
    }

    # Letters with context-sensitive mapping (initial vs inside-word)
    initial = {"є": "ye", "ю": "yu", "я": "ya", "ї": "yi"}
    inside = {"є": "ie", "ю": "iu", "я": "ia", "ї": "i"}

    # Merge into mapping by choosing a marker; we'll handle context at runtime
    m.update({k: v for k, v in inside.items()})
    # keep separate dicts for initial handling
    return {"base": m, "initial": initial, "inside": inside}


MAPPINGS = build_mappings()


def transliterate_word(word: str) -> str:
    """Transliterate a single word from Ukrainian Cyrillic to a Latin approximation.

    We handle context-sensitive letters (є, ю, я, ї) differently at word start.
    Capitalization is preserved by capitalizing the first Latin letter when the
    original word starts with an uppercase Cyrillic letter.
    """
    base = MAPPINGS["base"]
    initial = MAPPINGS["initial"]
    inside = MAPPINGS["inside"]

    out_chars = []
    prev_is_cyr = False
    for i, ch in enumerate(word):
        lower = ch.lower()
        is_upper = ch != lower
        if lower in initial:
            # Determine if at word start -> use initial mapping, else inside mapping
            use = (
                initial[lower]
                if (i == 0) or (not prev_is_cyr)
                else inside[lower]
            )
            mapped = use
        elif lower in base:
            mapped = base[lower]
        else:
            mapped = ch

        # preserve capitalization: if original char was uppercase, uppercase first letter
        if is_upper and mapped:
            # Uppercase only the first character of the mapped chunk
            mapped = mapped[0].upper() + mapped[1:]

        out_chars.append(mapped)
        prev_is_cyr = bool(re.match(r"[\u0400-\u04FF]", ch))

    return "".join(out_chars)


def transliterate_text(text: str) -> str:
    """Transliterate a text which may contain multiple words/punctuation.

    We split on word boundaries (keeping punctuation) and transliterate only tokens
    that contain Cyrillic letters.
    """
    if text is None:
        return text

    # Split into word tokens while keeping separators
    tokens = re.split(r"(\W+)", text, flags=re.UNICODE)
    out = []
    for tok in tokens:
        if CYRILLIC_RE.search(tok):
            out.append(transliterate_word(tok))
        else:
            out.append(tok)
    return "".join(out)


def find_text_elements(root: ET.Element):
    """Yield elements that contain Cyrillic text we want to transliterate.

    We look for any element whose .text contains Cyrillic characters. This keeps
    the routine robust to different MEI tag names (syl, syllable, lyric, etc.).
    """
    for el in root.iter():
        txt = el.text
        if not txt:
            continue
        if CYRILLIC_RE.search(txt):
            yield el


def process_tree(tree: ET.ElementTree) -> int:
    """Transliterate all matching elements in-place. Returns number of changed elements."""
    root = tree.getroot()
    changed = 0
    for el in find_text_elements(root):
        orig = el.text
        transl = transliterate_text(orig)
        if transl != orig:
            # preserve original in an attribute and set phon attribute
            # don't overwrite if user already has attributes
            if "orig" not in el.attrib:
                el.set("orig", orig)
            el.set("phon", transl)
            el.text = transl
            changed += 1
    return changed


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Transliterate Cyrillic lyrics in an MEI/XML to Latin phoneme-like text"
    )
    p.add_argument("infile", help="Input MEI or XML file")
    p.add_argument(
        "-o", "--outfile", help="Output file path. If omitted prints to stdout"
    )
    p.add_argument(
        "--inplace", action="store_true", help="Overwrite input file"
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        tree = ET.parse(args.infile)
    except ET.ParseError as e:
        print(f"Error parsing XML: {e}", file=sys.stderr)
        return 2

    changed = process_tree(tree)

    out_path = None
    if args.inplace:
        out_path = args.infile
    elif args.outfile:
        out_path = args.outfile

    if out_path:
        # Write back with XML declaration and UTF-8 encoding
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        print(f"Wrote {changed} transliterated elements to {out_path}")
    else:
        # Print to stdout
        ET.indent(tree, space="  ", level=0) if hasattr(ET, "indent") else None
        sys.stdout.buffer.write(
            ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
