# VidForge

Modular AI-powered video generation system. Takes data from multiple sources, composes structured video timelines using reusable effects and templates, and outputs to multiple platforms.

Built to run on GitHub Actions for free — no server, no database, just Python + ffmpeg.

## How It Works

1. **Define a recipe** (YAML) — what data, what style, which platforms
2. **Hamilton DAG** orchestrates the pipeline — fetch → process → compose → render → upload
3. **Reusable templates** (intro, outro, comparison, countdown) plug into a filmstrip
4. **One render, many targets** — same content outputs to YouTube, TikTok, Reels

## Architecture

```mermaid
graph LR
    R[Recipe YAML] --> S[Data Sources]
    S --> A[Asset Pipeline]
    A --> T[Timeline Compositor]
    T --> P[Platform Targets]
    P --> U[Upload]
```

See [`.ai/PLAN.md`](.ai/PLAN.md) for full architecture notes and AI working docs.

## Quick Start

```bash
pip install -e ".[all]"
vidforge generate --recipe config/recipes/anime_heights_dbz.yaml --target youtube
vidforge upload --platform youtube
```

## Pipeline DAG

```mermaid
graph TD
    recipe[Load Recipe] --> source[Fetch Data Source]
    source --> items[Item List]
    items --> dl[Download Images]
    dl --> validate[Validate Images]
    validate --> bg[Remove Backgrounds]
    items --> search[Search Music]
    search --> dl_music[Download Music]
    bg --> compose[Compose Timeline]
    dl_music --> compose
    compose --> render[Render Video]
    render --> upload[Upload]
    validate -.-> preview[HTML Preview]
    bg -.-> preview
```

## Project Structure

```
vidforge/
├── .ai/                    # AI planning docs (not for human review)
├── src/vidforge/
│   ├── sources/            # Data ingestion (Fandom, AniList, Jikan, custom)
│   ├── assets/             # Image processing, bg removal, music, caching
│   ├── effects/            # Reusable ffmpeg filter effects
│   ├── templates/          # Scene templates (intro, outro, comparison, etc.)
│   ├── compositor/         # Timeline builder + ffmpeg renderer
│   ├── targets/            # Platform output configs
│   └── upload/             # Platform publishing
├── config/
│   ├── recipes/            # Video recipes (YAML)
│   ├── characters/         # Character data files
│   └── targets/            # Target presets
├── .github/workflows/      # GitHub Actions (cron + manual)
└── tests/
```

## License

MIT
