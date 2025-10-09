#!/usr/bin/env python3
"""Batch-convert MEI/MusicXML files to MIDI using music21.

This script is conversion-only: transliteration is handled by
`synthesis-team/mei_translator.py` when available. The converter prefers
parseable transliterated MEIs placed under `synthesis-team/meis_trans` so the
two-stage pipeline (translate -> convert) can be run independently.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger("mei2midi")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _load_translator_module() -> object | None:
    try:
        base = Path(__file__).resolve().parent
        mod_path = base.joinpath("mei_translator.py")
        if not mod_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(
            "mei_translator", str(mod_path)
        )
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod
    except Exception:
        return None


# Attempt to load translator functions; fall back to identity functions.
_translator_mod = _load_translator_module()
if _translator_mod:
    # Support multiple possible function names in different versions of the
    # translator module. Provide safe defaults where names aren't present.
    ukrainian_to_ascii = getattr(
        _translator_mod,
        "ukrainian_to_ascii",
        getattr(
            _translator_mod, "transliterate_word", lambda w: (w or "").strip()
        ),
    )
    transliterate_mei_content = getattr(
        _translator_mod,
        "transliterate_mei_content",
        getattr(_translator_mod, "transliterate_text", lambda s: s),
    )
    transliterate_text = getattr(
        _translator_mod, "transliterate_text", lambda s: s
    )
else:

    def ukrainian_to_ascii(word: str) -> str:  # type: ignore[override]
        return (word or "").strip()

    def transliterate_mei_content(xml_text: str) -> str:  # type: ignore[override]
        return xml_text

    def transliterate_text(text: str) -> str:  # type: ignore[override]
        return text


SOURCE_DIR = Path(__file__).resolve().parent.joinpath("meis_phoneme")

OUTPUT_DIR = Path(__file__).resolve().parent.joinpath("midi")


def find_input_files(src: Path) -> list[Path]:
    patterns = [
        "**/*.mei",
        "**/*.mei.xml",
        "**/*.xml",
        "**/*.musicxml",
        "**/*.mxl",
    ]
    files: list[Path] = []
    for p in patterns:
        files.extend(src.glob(p))
    return sorted({f for f in files})


def try_music21(
    in_path: Path,
    out_path: Path,
    align_dir: Path | None = None,
    inject_phonemes: bool = False,
    transliterated_out: (
        Path | None
    ) = None,  # ignored; files already transliterated
) -> bool:
    """Parse input with music21 and write MIDI.

    If `transliterated_out` is provided, the function will save a transliterated
    .mei (and a same-suffix copy) inside that path and prefer parsing the
    transliterated copy. If the original input is an .mxl, a temporary .xml
    file will be created for parsing.
    """
    try:
        from music21 import converter, note, chord

        # We assume inputs in `meis_phoneme` are already transliterated/ready.
        parse_path = in_path
        temp_to_remove: Path | None = None
        # If the input is an .mxl (zipped), extract the inner XML to a temp file
        if in_path.suffix.lower() == ".mxl":
            try:
                with zipfile.ZipFile(in_path, "r") as zf:
                    xml_names = [
                        n for n in zf.namelist() if n.lower().endswith(".xml")
                    ]
                    if xml_names:
                        with zf.open(xml_names[0]) as inner:
                            try:
                                data = inner.read().decode("utf8", "replace")
                            except Exception:
                                data = inner.read().decode("latin1", "replace")
                        tf = tempfile.NamedTemporaryFile(
                            delete=False, suffix=".xml"
                        )
                        tf.write(data.encode("utf8"))
                        tf.flush()
                        tf.close()
                        parse_path = Path(tf.name)
                        temp_to_remove = parse_path
            except Exception:
                parse_path = in_path

        try:
            score = converter.parse(str(parse_path))
        finally:
            # remove temporary parse file if we created one
            if temp_to_remove is not None:
                try:
                    temp_to_remove.unlink()
                except Exception:
                    pass

        # Build alignments exclusively from score-attached lyrics when requested
        alignments = None
        if inject_phonemes:
            notes = list(
                score.recurse().getElementsByClass((note.Note, chord.Chord))
            )
            notes_with_lyrics = [
                n
                for n in notes
                if hasattr(n, "lyrics")
                and n.lyrics
                and getattr(n.lyrics[0], "text", "").strip()
            ]
            if not notes_with_lyrics:
                notes_with_lyrics = notes

            alignments = []
            for n in notes_with_lyrics:
                orig = (
                    getattr(n.lyrics[0], "text", "").strip()
                    if hasattr(n, "lyrics")
                    and n.lyrics
                    and getattr(n.lyrics[0], "text", "").strip()
                    else ""
                )
                # Files in meis_phoneme are already transliterated; use lyric text as-is
                ascii_ph = orig
                alignments.append(
                    {
                        "lyric_orig": orig,
                        "lyric_ascii": ascii_ph,
                        "note": {
                            "offset": float(n.offset),
                            "duration": float(n.quarterLength),
                        },
                    }
                )

            # apply ascii tokens back to the score notes (replace existing lyrics)
            if alignments:
                ascii_tokens = [a.get("lyric_ascii", "") for a in alignments]
                notes_with_lyrics = [
                    n
                    for n in notes
                    if hasattr(n, "lyrics")
                    and n.lyrics
                    and getattr(n.lyrics[0], "text", "").strip()
                ]
                for n, tok in zip(notes_with_lyrics, ascii_tokens):
                    if not tok:
                        continue
                    try:
                        if hasattr(n, "lyrics") and n.lyrics:
                            try:
                                n.lyrics[0].text = tok
                                continue
                            except Exception:
                                pass
                        n.addLyric(tok)
                    except Exception:
                        try:
                            n.lyrics = [note.Lyric(tok)]
                        except Exception:
                            pass

        out_path.parent.mkdir(parents=True, exist_ok=True)
        score.write("midi", fp=str(out_path))

        if inject_phonemes and alignments:
            try:
                inject_ascii_lyrics_mido(out_path, alignments)
            except Exception:
                logger.exception(
                    "Post-process lyric injection failed for %s", out_path
                )

        return True
    except Exception as exc:
        logger.exception("music21 conversion failed for %s: %s", in_path, exc)
        return False


def inject_ascii_lyrics_mido(midi_path: Path, align_file_or_list) -> bool:
    try:
        import mido

        def safe_midi_text(s: str) -> str:
            if s is None:
                return ""
            s = " ".join(s.split())
            s = s.replace("\u2013", "-").replace("\u2014", "-")
            s = s.replace("\u2018", "'").replace("\u2019", "'")
            s = s.replace("\u201c", '"').replace("\u201d", '"')
            s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
            return "".join((c if ord(c) < 256 else "?") for c in s)

        if isinstance(align_file_or_list, Path):
            if not align_file_or_list.exists():
                return False
            data = json.loads(align_file_or_list.read_text(encoding="utf8"))
            alignments = data.get("alignments", [])
        else:
            alignments = align_file_or_list
        if not alignments:
            return False

        mid = mido.MidiFile(str(midi_path))
        tpq = mid.ticks_per_beat

        align_events = []
        for a in alignments:
            off = a.get("note", {}).get("offset")
            text = a.get("lyric_ascii")
            if off is None or not text:
                continue
            ticks = int(round(float(off) * tpq))
            align_events.append((ticks, text))

        align_events.sort(key=lambda x: x[0])

        existing_events = []
        for ti, track in enumerate(mid.tracks):
            abs_t = 0
            for msg in track:
                abs_t += int(msg.time)
                if (
                    getattr(msg, "is_meta", False)
                    and getattr(msg, "type", "") == "lyrics"
                ):
                    existing_events.append((abs_t, msg.text))

        if not align_events and not existing_events:
            return False

        merged = []
        seen = set()
        for t, txt in align_events:
            merged.append((t, txt))
            seen.add((t, txt))
        for t, txt in existing_events:
            if (t, txt) in seen:
                continue
            merged.append((t, txt))

        if not merged:
            return False

        events = sorted(merged, key=lambda x: x[0])

        track_abs_msgs = []
        note_on_counts = []
        for track in mid.tracks:
            abs_tick = 0
            msgs = []
            note_on_count = 0
            for msg in track:
                abs_tick += int(msg.time)
                if (
                    getattr(msg, "is_meta", False)
                    and getattr(msg, "type", "") == "lyrics"
                ):
                    continue
                msgs.append((abs_tick, msg))
                if getattr(msg, "type", "") == "note_on":
                    note_on_count += 1
            track_abs_msgs.append(msgs)
            note_on_counts.append(note_on_count)

        try:
            target_index = int(
                max(range(len(note_on_counts)), key=lambda i: note_on_counts[i])
            )
        except Exception:
            target_index = 0

        lyric_events = [
            (
                t,
                mido.MetaMessage(
                    "lyrics", text=safe_midi_text(str(txt)), time=0
                ),
            )
            for t, txt in events
        ]

        merged_list = []
        existing = track_abs_msgs[target_index]
        i = j = 0
        while i < len(existing) or j < len(lyric_events):
            next_existing = existing[i] if i < len(existing) else (10**18, None)
            next_lyric = (
                lyric_events[j] if j < len(lyric_events) else (10**18, None)
            )
            if next_lyric[0] <= next_existing[0]:
                merged_list.append((next_lyric[0], next_lyric[1]))
                j += 1
            else:
                merged_list.append(next_existing)
                i += 1

        new_target_track = mido.MidiTrack()
        last_tick = 0
        for abs_tick, msg in merged_list:
            delta = abs_tick - last_tick
            if delta < 0:
                delta = 0
            cloned = msg.copy(time=delta) if hasattr(msg, "copy") else msg
            new_target_track.append(cloned)
            last_tick = abs_tick

        if not (
            new_target_track
            and getattr(new_target_track[-1], "type", "") == "end_of_track"
        ):
            new_target_track.append(mido.MetaMessage("end_of_track", time=0))

        new_tracks = []
        for idx, msgs in enumerate(track_abs_msgs):
            if idx == target_index:
                new_tracks.append(new_target_track)
            else:
                ttrack = mido.MidiTrack()
                last = 0
                for abs_t, msg in msgs:
                    delta = abs_t - last
                    if delta < 0:
                        delta = 0
                    cloned = (
                        msg.copy(time=delta) if hasattr(msg, "copy") else msg
                    )
                    ttrack.append(cloned)
                    last = abs_t
                if not (
                    ttrack and getattr(ttrack[-1], "type", "") == "end_of_track"
                ):
                    ttrack.append(mido.MetaMessage("end_of_track", time=0))
                new_tracks.append(ttrack)

        mid.tracks = new_tracks
        mid.save(str(midi_path))
        return True
    except Exception as exc:
        logging.getLogger("mei2midi").exception(
            "inject_ascii_lyrics_mido failed for %s: %s", midi_path, exc
        )
        return False


def convert(
    in_path: Path,
    out_dir: Path,
    align_dir: Path | None = None,
    inject_phonemes: bool = False,
    transliterated_out: Path | None = None,
) -> tuple[bool, str]:
    out_path = out_dir / (in_path.stem + ".mid")
    if try_music21(
        in_path,
        out_path,
        align_dir=align_dir,
        inject_phonemes=inject_phonemes,
        transliterated_out=transliterated_out,
    ):
        return True, "music21"
    return False, "music21-failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert MEI/MusicXML files to MIDI"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=SOURCE_DIR,
        help="Input directory to scan",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output dir for MIDI files",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--inject-phonemes",
        action="store_true",
        help="Build ASCII phoneme tokens from score lyrics and inject them into MIDI",
    )
    parser.add_argument(
        "--align-dir",
        type=Path,
        default=None,
        help="Directory containing .align.json files (unused by this converter)",
    )
    args = parser.parse_args(argv)

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    src = args.input_dir
    out = args.output_dir

    if not src.exists():
        logger.error("Input directory does not exist: %s", src)
        return 2

    files = find_input_files(src)
    if not files:
        logger.info("No files found in %s", src)
        return 0

    out.mkdir(parents=True, exist_ok=True)
    # Directory where transliterated artifacts are stored (created by the
    # translation step). Default to `meis_phoneme` if available.
    MEIS_TRANS_DIR = Path(__file__).resolve().parent.joinpath("meis_phoneme")
    meis_trans_root = MEIS_TRANS_DIR
    meis_trans_root.mkdir(parents=True, exist_ok=True)
    successes = 0
    failures: list[str] = []

    for f in files:
        out_path = out / (f.stem + ".mid")
        if out_path.exists() and not args.overwrite:
            logger.info("Skipping (exists): %s", out_path.name)
            continue

        try:
            rel = f.relative_to(src)
        except Exception:
            rel = f.name
        translit_out = meis_trans_root.joinpath(rel)
        translit_out.parent.mkdir(parents=True, exist_ok=True)

        ok, method = convert(
            f,
            out,
            align_dir=args.align_dir,
            inject_phonemes=args.inject_phonemes,
            transliterated_out=translit_out,
        )
        if ok:
            successes += 1
            logger.info(
                "Converted %s -> %s via %s", f.name, out_path.name, method
            )
        else:
            failures.append(str(f))
            logger.warning("Failed to convert %s", f.name)

    logger.info("Done. Converted: %d  Failed: %d", successes, len(failures))
    if failures:
        logger.info("Failed files: %s", failures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
