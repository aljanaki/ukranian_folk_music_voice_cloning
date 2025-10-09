
Short usage — transcribe MusicXML (.mxl/.xml) to transliterated XML and convert to MIDI

Prerequisites
- Bash shell

Commands

1) Create and activate a Python virtual environment (only if you don't already have `.venv`)

```bash
# create venv in repo root (one-time)
python3 -m venv .venv

# activate
source .venv/bin/activate
```

2) Install required packages into the activated venv

```bash
pip install --upgrade pip
pip install music21 mido
```

3) Transcribe / transliterate MusicXML files into a transliterated folder

Set a placeholder for your MusicXML source directory and run the batch script. The script accepts the source path as its first argument.

```bash
# Example: set a variable pointing to the folder that contains your .mxl/.xml files
MUSICXML_DIR="/path/to/your/musicxml_folder"

# Run the batch transcription (optionally limit with --limit)
python3 synthesis-team/batch_musicxml_to_mei_phon.py "$MUSICXML_DIR"

# Fast test with a limit:
python3 synthesis-team/batch_musicxml_to_mei_phon.py "$MUSICXML_DIR" --limit 20
```

4) Convert the transliterated XML files to MIDI

Set placeholders for transliterated input and MIDI output directories, then run the converter.

```bash
# Example variables (set to where your transliterated XMLs live and where you want MIDI):
TRANSLIT_DIR="/path/to/transliterated_xml_folder"   # e.g. synthesis-team/meis_phoneme
MIDI_DIR="/path/to/output_midi_folder"             # e.g. synthesis-team/midi

python3 synthesis-team/mei_to_midi.py --input-dir "$TRANSLIT_DIR" --output-dir "$MIDI_DIR"

# Options:
# --overwrite        : overwrite existing .mid files
# --verbose          : more logging
# --inject-phonemes  : inject lyric tokens into the produced MIDI (uses existing lyric text)
```

That's it — after step 4 the MIDI files will be in `synthesis-team/midi`.
