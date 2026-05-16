"""Command-line entry point.

用法:
    manulife discover           # 由宏利 API 抓取最新基金清單寫入 funds.yaml
    manulife fetch              # 抓取最新 NAV + 宏觀數據
    manulife analyze            # 重新計算指標
    manulife report weekly      # 生成每週 HTML 報告
    manulife report monthly
    manulife status             # 查看數據庫狀態
"""

from __future__ import annotations

import logging

import click
import yaml
from rich.console import Console
from rich.table import Table

from .analysis.metrics import compute_fund_metrics, metrics_to_rows
from .config import CONFIG_DIR, load_settings
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
@click.option("--verbose", "-v", is_flag=True, help="詳細日誌。")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """宏利投資分析自動化。"""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["settings"] = load_settings()
    ctx.obj["db"] = Database(ctx.obj["settings"].storage_db)


@cli.command()
@click.option("--product-id", type=int, default=None,
              help="只 discover 指定 productId（預設 settings.yaml 入面全部）。")
@click.option("--write/--no-write", default=False,
              help="寫入 config/funds.yaml（會覆蓋）。預設只 dry-run 印出。")
@click.pass_context
def discover(ctx: click.Context, product_id: int | None, write: bool) -> None:
    """由宏利官方 API 自動抓基金清單。

    讀取 settings.yaml 入面嘅 manulife.products，逐個 productId 叫
    v2/fundlist 端點，輸出基金清單。如果加 --write，會更新 funds.yaml。
    """
    settings = ctx.obj["settings"]
    fetcher = build_manulife_fetcher(settings.http, settings.manulife)

    targets = settings.manulife.products
    if product_id is not None:
        targets = {product_id: targets.get(product_id, "")}

    all_funds: list[dict] = []
    for pid, name in targets.items():
        console.print(f"[bold cyan]Discover productId={pid} ({name})…[/]")
        infos = fetcher.fetch_fund_list(pid, name)
        for info in infos:
            all_funds.append(
                {
                    "code": info.code,
                    "isin": info.isin,
                    "name": info.name_en,
                    "name_zh": info.name_zh,
                    "category": info.category,
                    "region": info.region,
                    "currency": info.currency,
                    "risk_level": info.risk_level,
                }
            )
        console.print(f"  → 收集咗 {len(infos)} 隻基金")

    if not all_funds:
        console.print("[yellow]Discover 失敗 — 可能網絡受限，或者宏利端點結構改咗。[/]")
        console.print("[yellow]檢查 src/manulife_analyzer/data/manulife.py 入面嘅 field aliases。[/]")
        return

    if write:
        path = CONFIG_DIR / "funds.yaml"
        backup = path.with_suffix(".yaml.bak")
        if path.exists():
            backup.write_bytes(path.read_bytes())
            console.print(f"[dim]已備份原檔到 {backup}[/]")
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {"funds": all_funds}, fh, allow_unicode=True, sort_keys=False
            )
        console.print(f"[green]寫入 {path}（共 {len(all_funds)} 隻基金）[/]")
    else:
        console.print("[dim]Dry-run。加 --write 寫入 config/funds.yaml。[/]")
        for f in all_funds[:10]:
            console.print(f"  · {f['code']} {f.get('name_zh') or f['name']} "
                          f"[{f['category']}/{f['region']}]")
        if len(all_funds) > 10:
            console.print(f"  … 仲有 {len(all_funds) - 10} 隻")


@cli.command()
@click.option(
    "--source",
    type=click.Choice(["all", "manulife", "yahoo", "fred", "world_bank"]),
    default="all",
)
@click.option(
    "--manulife-mode",
    type=click.Choice(["snapshot", "history"]),
    default="snapshot",
    help="snapshot = 只抓最新 NAV（穩陣）；history = 嘗試抓歷史 NAV（端點唔穩定）",
)
@click.pass_context
def fetch(ctx: click.Context, source: str, manulife_mode: str) -> None:
    """抓取最新數據入 DB。"""
    settings = ctx.obj["settings"]
    db: Database = ctx.obj["db"]
    http = HttpClient(
        user_agent=settings.http.user_agent,
        timeout=settings.http.timeout,
        cache_hours=settings.http.cache_hours,
        rate_limit_seconds=settings.http.rate_limit_seconds,
    )

    if source in ("all", "manulife"):
        console.print("[bold cyan]抓取宏利基金 NAV…[/]")
        fetcher = build_manulife_fetcher(settings.http, settings.manulife)
        if manulife_mode == "snapshot":
            points = fetcher.fetch_latest_navs(settings.manulife.products)
        else:
            points = fetcher.fetch_history_many(
                settings.funds, product_id=next(iter(settings.manulife.products))
            )
        n = db.upsert_prices(points)
        db.log_fetch("manulife", "ok" if n else "empty", f"{n} rows")
        console.print(f"  → 寫入 {n} 條價格")

    if source in ("all", "yahoo"):
        console.print("[bold cyan]抓取 Yahoo 基準價格（含板塊 ETF）…[/]")
        fund_benchmarks = [f.benchmark for f in settings.funds if f.benchmark]
        tickers = sorted(
            set(settings.benchmark_tickers)
            | set(fund_benchmarks)
            | set(settings.theme_tickers)
        )
        points = fetch_yahoo_prices(tickers, lookback_days=400)
        n = db.upsert_prices(points)
        db.log_fetch("yahoo", "ok" if n else "empty", f"{n} rows")
        console.print(f"  → 寫入 {n} 條（{len(tickers)} 個 ticker）")

    if source in ("all", "fred"):
        console.print("[bold cyan]抓取 FRED 宏觀數據…[/]")
        points = fetch_fred_series(
            list(settings.fred_series.keys()), settings.fred_api_key
        )
        n = db.upsert_macro(points)
        db.log_fetch("fred", "ok" if n else "skipped", f"{n} rows")
        console.print(f"  → 寫入 {n} 條宏觀數據")

    if source in ("all", "world_bank"):
        console.print("[bold cyan]抓取世界銀行指標…[/]")
        points = fetch_world_bank(http)
        n = db.upsert_macro(points)
        db.log_fetch("world_bank", "ok" if n else "empty", f"{n} rows")
        console.print(f"  → 寫入 {n} 條")

    console.print("[green]完成。[/]")


@cli.command()
@click.pass_context
def analyze(ctx: click.Context) -> None:
    """重新計算所有基金嘅指標。"""
    settings = ctx.obj["settings"]
    db: Database = ctx.obj["db"]
    prices = db.prices_df()
    if prices.empty:
        console.print("[yellow]DB 入面冇價格 — 先行 `manulife fetch`。[/]")
        return

    a = settings.analysis
    symbols = set(f.code for f in settings.funds) | set(prices["symbol"].unique())
    rows: list[tuple] = []
    for symbol in symbols:
        slice_ = prices[prices["symbol"] == symbol]
        m = compute_fund_metrics(
            slice_,
            symbol=symbol,
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
    console.print(f"[green]寫入 {n} 條指標。[/]")


@cli.command()
@click.argument("kind", type=click.Choice(["weekly", "monthly"]))
@click.pass_context
def report(ctx: click.Context, kind: str) -> None:
    """生成 HTML 報告。"""
    settings = ctx.obj["settings"]
    db: Database = ctx.obj["db"]
    path = build_report(db, settings, kind)
    console.print(f"[green]報告已生成：[/] {path}")


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """查看 DB 入面而家有咩數據。"""
    db: Database = ctx.obj["db"]
    settings = ctx.obj["settings"]

    prices = db.prices_df()
    macro = db.macro_df()

    t = Table(title="價格數據")
    t.add_column("Symbol")
    t.add_column("筆數", justify="right")
    t.add_column("最早")
    t.add_column("最新")
    if not prices.empty:
        grouped = prices.groupby("symbol")["asof"].agg(["count", "min", "max"])
        for sym, row in grouped.iterrows():
            t.add_row(sym, str(int(row["count"])), str(row["min"].date()), str(row["max"].date()))
    console.print(t)

    t2 = Table(title="宏觀數據")
    t2.add_column("Series")
    t2.add_column("筆數", justify="right")
    t2.add_column("最新值", justify="right")
    if not macro.empty:
        for sid, sub in macro.groupby("series_id"):
            last = sub.sort_values("asof").iloc[-1]
            t2.add_row(sid, str(len(sub)), f"{float(last['value']):.3f}")
    console.print(t2)

    console.print(f"[dim]DB:[/] {settings.storage_db}")


if __name__ == "__main__":
    cli()
