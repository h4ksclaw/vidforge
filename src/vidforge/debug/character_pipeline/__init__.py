"""Debug tests for the character height pipeline.

Each module is runnable via: python -m vidforge.debug.character_pipeline.<module>

- height    — test parse_height against edge cases and real wiki data
- images    — test image scoring, bg removal, and quality filters
- discovery — test character discovery, skip words, and height fetching
- scaling   — test height-to-pixel scaling with visual bounding box debug
"""
