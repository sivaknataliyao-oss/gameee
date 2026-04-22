"""Typer CLI entrypoint: scan / process / run / rights."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from src.core import config
from src.core.models import LengthProfile, Source, Story
from src.core.storage import (
    StoryRow,
    get_story,
    mark_used,
    metrics_to_json,
    top_unused,
    upsert_story,
)
from src.pipeline import RunOptions, process_one
from src.rights.manager import ensure_asked, is_cleared, record_response
from src.sources.registry import all_adapters, by_name

console = Console()
app = typer.Typer(add_completion=False, no_args_is_help=True)


def _setup_logging() -> None:
    level = os.getenv("GAMEEE_LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )


def _story_to_row(s: Story) -> StoryRow:
    return StoryRow(
        id=s.id, source=s.source.value, source_id=s.source_id,
        permalink=s.permalink, author=s.author, title=s.title, text=s.text,
        lang_detected=s.lang_detected.value, nsfw=s.nsfw,
        created_at=s.created_at, fetched_at=s.fetched_at,
        metrics_json=metrics_to_json(s.metrics.model_dump()),
        growth_score=s.growth_score, long_form_potential=s.long_form_potential,
    )


@app.command()
def scan(source: str = typer.Option("all", help="reddit | twitter | threads | all"),
         limit: int = 100) -> None:
    """Pull candidates from sources and persist them to the DB."""
    _setup_logging()

    async def _go() -> int:
        adapters = all_adapters() if source == "all" else [by_name(source)]
        total = 0
        for a in adapters:
            try:
                stories = await a.fetch(limit=limit)
                for s in stories:
                    upsert_story(_story_to_row(s))
                console.print(f"[green]{a.name}[/green]: ingested {len(stories)}")
                total += len(stories)
            except Exception as exc:
                console.print(f"[red]{a.name}[/red] failed: {exc}")
            finally:
                close = getattr(a, "close", None)
                if close:
                    await close()
        return total

    n = asyncio.run(_go())
    console.print(f"[bold]total ingested:[/bold] {n}")


@app.command()
def rank(limit: int = 20) -> None:
    """Show top unused stories by growth score."""
    _setup_logging()
    rows = top_unused(limit=limit)
    table = Table(title=f"Top {limit} unused stories")
    for col in ("id", "source", "score", "long%", "title"):
        table.add_column(col)
    for r in rows:
        title = (r.title or "")[:80]
        table.add_row(r.id, r.source, f"{r.growth_score:.1f}",
                       f"{r.long_form_potential*100:.0f}", title)
    console.print(table)


@app.command()
def ask(story_id: str, lang: str = "ru") -> None:
    """Mark a story as 'permission requested' and print the message to send."""
    _setup_logging()
    row = get_story(story_id)
    if not row:
        raise typer.Exit(code=1)
    story = _row_to_story(row)
    p = ensure_asked(story, lang=lang)
    console.print(f"[yellow]Ask {story.author}:[/yellow]\n\n{p.text}\n")
    console.print(f"[dim]source: {story.permalink}[/dim]")


@app.command()
def grant(story_id: str, text: str = "Yes, I give permission",
          evidence: str | None = None) -> None:
    """Record author's permission (from a DM screenshot / link)."""
    _setup_logging()
    record_response(story_id, granted=True, text=text, evidence_url=evidence)
    console.print(f"[green]granted[/green]: {story_id}")


@app.command()
def deny(story_id: str, text: str = "denied") -> None:
    _setup_logging()
    record_response(story_id, granted=False, text=text)
    console.print(f"[red]denied[/red]: {story_id}")


@app.command()
def run(
    story_id: str | None = typer.Option(None, help="specific story id; else pick top unused"),
    research: bool = typer.Option(False, "--research/--no-research",
                                  help="bypass rights gate for internal rendering only"),
    profile: str = typer.Option("auto", help="short | long | auto"),
    publish: bool = typer.Option(False, help="upload long video to YouTube"),
) -> None:
    """Render one story end-to-end. Default: pick top cleared story."""
    _setup_logging()
    if story_id:
        row = get_story(story_id)
    else:
        # pick highest-scoring story that's either cleared or in research mode
        candidates = top_unused(limit=50)
        row = None
        for c in candidates:
            if research or is_cleared(c.id):
                row = c
                break
    if not row:
        console.print("[red]no eligible story[/red]")
        raise typer.Exit(code=1)

    story = _row_to_story(row)
    opts = RunOptions(
        research_mode=research,
        publish_youtube=publish,
        profile={"short": LengthProfile.SHORT, "long": LengthProfile.LONG}.get(profile, LengthProfile.SHORT),
    )
    artifacts = process_one(story, opts)
    if artifacts is None:
        console.print("[red]pipeline returned no artifacts[/red]")
        raise typer.Exit(code=1)
    console.print(artifacts.model_dump_json(indent=2))


@app.command()
def loop(
    interval_sec: int = typer.Option(180, help="scan cadence"),
    max_renders: int = typer.Option(3, help="max renders per iteration"),
    research: bool = False,
) -> None:
    """Run scan + render in a loop (for cron/systemd alternatives)."""
    import time

    _setup_logging()
    while True:
        asyncio.run(_scan_all())
        rendered = 0
        for c in top_unused(limit=20):
            if rendered >= max_renders:
                break
            if not (research or is_cleared(c.id)):
                continue
            story = _row_to_story(c)
            process_one(story, RunOptions(research_mode=research))
            rendered += 1
        time.sleep(interval_sec)


async def _scan_all() -> None:
    for a in all_adapters():
        try:
            stories = await a.fetch(limit=100)
            for s in stories:
                upsert_story(_story_to_row(s))
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]{a.name}[/red] {exc}")
        finally:
            close = getattr(a, "close", None)
            if close:
                await close()


def _row_to_story(row: StoryRow) -> Story:
    from src.core.models import Lang, Metrics
    metrics = Metrics(**json.loads(row.metrics_json or "{}"))
    return Story(
        id=row.id,
        source=Source(row.source),
        source_id=row.source_id,
        permalink=row.permalink,
        author=row.author,
        title=row.title,
        text=row.text,
        lang_detected=Lang(row.lang_detected),
        nsfw=row.nsfw,
        created_at=row.created_at,
        fetched_at=row.fetched_at,
        metrics=metrics,
        growth_score=row.growth_score,
        long_form_potential=row.long_form_potential,
    )


if __name__ == "__main__":
    app()
