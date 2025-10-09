#!/usr/bin/env python3
"""Batch convert MusicXML files to MEI and transliterate Cyrillic lyrics to phonemes.

Scans a source directory for musicxml files, converts each to MEI via music21,
transliterates Cyrillic text using the existing `mei_translator.py` functions,
and writes the resulting MEI/XML files to `synthesis-team/meis_phoneme`.

This script does not embed a hardcoded default source folder. Provide the
source directory as the first positional argument, or set the environment
variable `MUSICXML_DIR` and run without arguments. This keeps the repository
free of machine-specific absolute paths.
"""

from __future__ import annotations

import importlib.util
import sys
import os
from pathlib import Path
import tempfile
import traceback
from xml.etree import ElementTree as ET


HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.joinpath("meis_phoneme")


def load_translator(translator_path: Path):
    """Dynamically load the user's mei_translator.py module from path and return module object."""
    spec = importlib.util.spec_from_file_location(
        "mei_translator_user", str(translator_path)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load translator from {translator_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # expect mod.process_tree to exist
    if not hasattr(mod, "process_tree"):
        raise AttributeError(
            "Loaded translator module does not expose process_tree(tree)"
        )
    return mod


def convert_and_transliterate(
    src_file: Path, out_file: Path, translator_mod
) -> bool:
    """Convert single MusicXML file to MEI, transliterate, and write to out_file.

    Returns True on success.
    """
    try:
        import music21
    except Exception as e:
        print("music21 is required but not available:", e, file=sys.stderr)
        return False

    try:
        score = music21.converter.parse(str(src_file))
    except Exception as e:
        print(f"Failed to parse {src_file.name}: {e}")
        return False
    # write a temporary file for music21 export (suffix arbitrary)
    with tempfile.NamedTemporaryFile(suffix=".mei", delete=False) as tf:
        tmp_path = Path(tf.name)

    try:
        # Try to ask music21 to export to MEI
        score.write("mei", fp=str(tmp_path))
    except Exception as e:
        # music21 may not support MEI export in this environment. Fall back to
        # transliterating the original MusicXML directly and writing that XML
        # to the output path. We'll name outputs with .xml since they are XML.
        print(
            f"music21 failed to write MEI for {src_file.name}: {e}. Falling back to direct XML transliteration."
        )
        try:
            tmp_path.unlink()
        except Exception:
            pass

        try:
            # Directly parse the original MusicXML and transliterate text nodes
            tree = ET.parse(str(src_file))
            changed = translator_mod.process_tree(tree)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            tree.write(str(out_file), encoding="utf-8", xml_declaration=True)
            print(
                f"Wrote (fallback) {out_file.name} (transliterated {changed} elements)"
            )
            return True
        except Exception as ex:
            print(f"Fallback transliteration failed for {src_file.name}: {ex}")
            traceback.print_exc()
            return False

    # If we reached here, music21 wrote tmp_path; parse it and transliterate
    try:
        tree = ET.parse(str(tmp_path))
        changed = translator_mod.process_tree(tree)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        tree.write(str(out_file), encoding="utf-8", xml_declaration=True)
        print(f"Wrote {out_file.name} (transliterated {changed} elements)")
        return True
    except Exception as e:
        print(f"Failed processing MEI for {src_file.name}: {e}")
        traceback.print_exc()
        return False
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Batch convert MusicXML to transliterated MEI phonemes"
    )
    p.add_argument(
        "src",
        nargs="?",
        default=None,
        help=(
            "Source folder containing MusicXML files. If omitted, the environment "
            "variable MUSICXML_DIR will be used (if set)."
        ),
    )
    p.add_argument(
        "-o",
        "--outdir",
        default=str(OUT_DIR),
        help="Output folder for MEI files",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of files processed (0 = no limit)",
    )
    args = p.parse_args(argv)

    # Resolve source directory: positional argument > MUSICXML_DIR env var
    src_value = args.src or os.environ.get("MUSICXML_DIR")
    if not src_value:
        print(
            "No source directory specified. Pass the source folder as the first argument, or set MUSICXML_DIR.",
            file=sys.stderr,
        )
        return 2

    src_dir = Path(src_value)
    out_dir = Path(args.outdir)

    if not src_dir.exists() or not src_dir.is_dir():
        print(
            "Source directory does not exist or is not a directory:",
            src_dir,
            file=sys.stderr,
        )
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    # Load translator from synthesis-team/mei_translator.py
    translator_path = HERE.joinpath("mei_translator.py")
    try:
        translator_mod = load_translator(translator_path)
    except Exception as e:
        print("Failed to load mei_translator.py:", e, file=sys.stderr)
        return 3

    # collect musicxml-like files
    patterns = ["*.xml", "*.musicxml", "*.mxl"]
    files = []
    for ptn in patterns:
        files.extend(sorted(src_dir.glob(ptn)))

    if not files:
        print("No MusicXML files found in", src_dir)
        return 0

    limit = args.limit if args.limit > 0 else None
    count = 0
    for f in files[:limit]:
        out_name = f.with_suffix(".xml").name
        out_path = out_dir.joinpath(out_name)
        ok = convert_and_transliterate(f, out_path, translator_mod)
        if ok:
            count += 1

    print(
        f"Done. Processed {count} of {len(files)} files. Output in: {out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
