"""Command-line entry point.

Usage:
    manulife fetch              # pull latest data
    manulife analyze            # recompute metrics
    manulife report weekly      # build HTML report
    manulife report monthly
"""

from __future__ import annotations

import logging

import click
from rich.console import Console
from rich.table import Table

from .analysis.metrics import compute_fund_metrics, metrics_to_rows
from .config import load_settings
from .data.fred import fetch_fred_series
from .data.http import HttpClient
from .data.manulife import build_fetcher as build_manulife_fetcher
from .data.world_bank import fetch_world_bank
from .data.yahoo import fetch_yahoo_prices
from .reports import build_report
from .storage import Database

LOG = logging.getLogger(__name__)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Verbose logs.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Manulife Analyzer."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["settings"] = load_settings()
    ctx.obj["db"] = Database(ctx.obj["settings"].storage_db)


@cli.command()
@click.option(
    "--source",
    type=click.Choice(["all", "manulife", "yahoo", "fred", "world_bank"]),
    default="all",
)
@click.pass_context
def fetch(ctx: click.Context, source: str) -> None:
    """Pull latest data from configured sources into the local DB."""
    settings = ctx.obj["settings"]
    db: Database = ctx.obj["db"]
    http = HttpClient(
        user_agent=settings.http.user_agent,
        timeout=settings.http.timeout,
        cache_hours=settings.http.cache_hours,
        rate_limit_seconds=settings.http.rate_limit_seconds,
    )

    if source in ("all", "manulife"):
        console.print("[bold cyan]Fetching Manulife NAVs…[/]")
        fetcher = build_manulife_fetcher(settings.http)
        points = fetcher.fetch_many(settings.funds)
        n = db.upsert_prices(points)
        db.log_fetch("manulife", "ok" if n else "empty", f"{n} rows")
        console.print(f"  → wrote {n} price points")

    if source in ("all", "yahoo"):
        console.print("[bold cyan]Fetching Yahoo benchmark prices…[/]")
        fund_benchmarks = [f.benchmark for f in settings.funds if f.benchmark]
        tickers = sorted(set(settings.benchmark_tickers) | set(fund_benchmarks))
        points = fetch_yahoo_prices(tickers, lookback_days=400)
        n = db.upsert_prices(points)
        db.log_fetch("yahoo", "ok" if n else "empty", f"{n} rows")
        console.print(f"  → wrote {n} price points across {len(tickers)} tickers")

    if source in ("all", "fred"):
        console.print("[bold cyan]Fetching FRED macro series…[/]")
        points = fetch_fred_series(
            list(settings.fred_series.keys()), settings.fred_api_key
        )
        n = db.upsert_macro(points)
        db.log_fetch("fred", "ok" if n else "skipped", f"{n} rows")
        console.print(f"  → wrote {n} macro points")

    if source in ("all", "world_bank"):
        console.print("[bold cyan]Fetching World Bank indicators…[/]")
        points = fetch_world_bank(http)
        n = db.upsert_macro(points)
        db.log_fetch("world_bank", "ok" if n else "empty", f"{n} rows")
        console.print(f"  → wrote {n} macro points")

    console.print("[green]Done.[/]")


@cli.command()
@click.pass_context
def analyze(ctx: click.Context) -> None:
    """Recompute per-fund metrics from stored prices."""
    settings = ctx.obj["settings"]
    db: Database = ctx.obj["db"]
    prices = db.prices_df()
    if prices.empty:
        console.print("[yellow]No prices in DB — run `manulife fetch` first.[/]")
        return

    a = settings.analysis
    rows: list[tuple] = []
    for fund in settings.funds:
        slice_ = prices[prices["symbol"] == fund.code]
        m = compute_fund_metrics(
            slice_,
            symbol=fund.code,
            return_windows=a.return_windows_days,
            vol_window=a.volatility_window_days,
            sharpe_window=a.sharpe_window_days,
            drawdown_window=a.drawdown_window_days,
        )
        if m is None:
            continue
        for s, metric, asof, v in metrics_to_rows(m):
            rows.append((s, metric, asof if hasattr(asof, "year") else asof.date(), v))

    n = db.upsert_metrics(rows)
    console.print(f"[green]Wrote {n} metric rows.[/]")


@cli.command()
@click.argument("kind", type=click.Choice(["weekly", "monthly"]))
@click.pass_context
def report(ctx: click.Context, kind: str) -> None:
    """Generate an HTML report."""
    settings = ctx.obj["settings"]
    db: Database = ctx.obj["db"]
    path = build_report(db, settings, kind)
    console.print(f"[green]Report written:[/] {path}")


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show what data is currently in the DB."""
    db: Database = ctx.obj["db"]
    settings = ctx.obj["settings"]

    prices = db.prices_df()
    macro = db.macro_df()

    t = Table(title="Prices by symbol")
    t.add_column("Symbol")
    t.add_column("Points", justify="right")
    t.add_column("Earliest")
    t.add_column("Latest")
    if not prices.empty:
        grouped = prices.groupby("symbol")["asof"].agg(["count", "min", "max"])
        for sym, row in grouped.iterrows():
            t.add_row(sym, str(int(row["count"])), str(row["min"].date()), str(row["max"].date()))
    console.print(t)

    t2 = Table(title="Macro series")
    t2.add_column("Series")
    t2.add_column("Points", justify="right")
    t2.add_column("Latest value", justify="right")
    if not macro.empty:
        for sid, sub in macro.groupby("series_id"):
            last = sub.sort_values("asof").iloc[-1]
            t2.add_row(sid, str(len(sub)), f"{float(last['value']):.3f}")
    console.print(t2)

    console.print(f"[dim]DB:[/] {settings.storage_db}")


if __name__ == "__main__":
    cli()
