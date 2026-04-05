"""
CLI entry point for sfmm.

Commands:
  sfmm discover     — find upcoming sports events on Polymarket
  sfmm run          — start quoting (pre-game and/or live)
  sfmm status       — show current state
"""

from __future__ import annotations

import asyncio
import logging
import sys

import click
from rich.console import Console
from rich.table import Table

from sfmm.config import load_config
from sfmm.execution.clob import ClobExecutor
from sfmm.risk.limits import RiskManager

console = Console()


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--config", "-c", default=None, help="Path to config.toml")
@click.option("--verbose", "-v", is_flag=True, help="Debug logging")
@click.pass_context
def main(ctx, config, verbose):
    """sfmm — Sports market making for Polymarket liquidity rewards."""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose


@main.command()
@click.pass_context
def discover(ctx):
    """Find upcoming sports events on Polymarket."""
    asyncio.run(_discover())


async def _discover():
    import httpx
    from sfmm.feeds.calendar import discover_sports_events

    console.print("\n[bold]Discovering sports events on Polymarket...[/bold]\n")

    async with httpx.AsyncClient() as client:
        games = await discover_sports_events(client)

    if not games:
        console.print("[yellow]No active sports events found.[/yellow]")
        return

    table = Table(title=f"Sports Events ({len(games)} found)")
    table.add_column("Sport", style="cyan", width=12)
    table.add_column("Event", width=40)
    table.add_column("Markets", justify="right", width=8)
    table.add_column("Mid", justify="right", width=8)
    table.add_column("Volume 24h", justify="right", width=12)
    table.add_column("Liquidity", justify="right", width=12)

    for game in games[:30]:
        mid_str = ""
        vol_str = ""
        liq_str = ""
        if game.markets:
            m = game.markets[0]
            mid_str = f"{m.current_mid:.2f}"
            vol_str = f"${m.volume_24h:,.0f}" if m.volume_24h else "-"
            liq_str = f"${m.liquidity:,.0f}" if m.liquidity else "-"

        table.add_row(
            game.sport.value,
            game.title[:40],
            str(len(game.markets)),
            mid_str,
            vol_str,
            liq_str,
        )

    console.print(table)
    console.print()


@main.command()
@click.option("--mode", type=click.Choice(["pre", "live", "auto"]), default="auto")
@click.option("--dry-run", is_flag=True, help="Log orders without placing them")
@click.option("--market", "-m", default=None, help="Specific market condition_id")
@click.pass_context
def run(ctx, mode, dry_run, market):
    """Start quoting. Modes: pre (pre-game only), live (live only), auto (both)."""
    config = load_config(ctx.obj["config_path"], dry_run=dry_run)

    if dry_run:
        console.print("[yellow]DRY RUN — no orders will be placed[/yellow]\n")

    if not dry_run and not config.clob.private_key:
        console.print("[red]POLYMARKET_PRIVATE_KEY not set. Use --dry-run or set the env var.[/red]")
        sys.exit(1)

    asyncio.run(_run(config, mode, market))


async def _run(config, mode: str, market_filter: str | None):
    import httpx
    from sfmm.feeds.calendar import discover_sports_events
    from sfmm.engine.pregame import PregameEngine
    from sfmm.core.types import Phase

    executor = ClobExecutor(config.clob, dry_run=config.dry_run)
    risk = RiskManager(config.risk)

    # Discover games
    console.print("[bold]Discovering sports events...[/bold]")
    async with httpx.AsyncClient() as client:
        games = await discover_sports_events(client)

    if market_filter:
        games = [g for g in games if any(m.condition_id == market_filter for m in g.markets)]

    if not games:
        console.print("[yellow]No games found to quote.[/yellow]")
        return

    console.print(f"Found [bold]{len(games)}[/bold] games. Starting engines...\n")

    # For now: run pre-game on all discovered games
    engines = []
    for game in games[:5]:  # cap at 5 games initially
        game.phase = Phase.PRE
        engine = PregameEngine(
            game=game,
            executor=executor,
            risk=risk,
            poll_interval=config.poll_interval_pre,
            max_position=config.max_position_per_market,
        )
        engines.append(engine)
        console.print(f"  [green]PRE[/green] {game.title} ({len(game.markets)} markets)")

    console.print()

    # Run all engines concurrently
    try:
        await asyncio.gather(*[e.run() for e in engines])
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
        for e in engines:
            await e.stop()


@main.command()
def status():
    """Show current quoting status."""
    console.print("[yellow]Status tracking not yet implemented — use logs.[/yellow]")


if __name__ == "__main__":
    main()
