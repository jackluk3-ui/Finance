# Manulife Analyzer (宏利投资分析自动化)

A data pipeline for tracking Manulife ILAS (investment-linked) and savings-plan
fund performance, joining it with global macro indicators, and producing weekly
and monthly observation reports.

> **This tool produces market observations and quantitative signals — not
> personalised investment advice.** Final recommendations to clients must be
> reviewed and signed off by a licensed adviser. See "Compliance" below.

## What it does

1. **Fetch** daily NAVs for a configurable universe of Manulife-linked funds
   plus reference indices (S&P 500, MSCI World, US Aggregate Bond, etc.).
2. **Fetch** global macro series: US rates, CPI, unemployment (FRED); global
   GDP (World Bank); benchmark prices (Yahoo Finance).
3. **Store** everything in a local SQLite database (`data/manulife.db`).
4. **Analyze** — returns, rolling volatility, Sharpe, max drawdown, momentum
   ranks, macro regime signals (rate-cycle turning points, yield-curve, CPI
   trend).
5. **Report** — HTML (and optional PDF) for weekly market observations and a
   richer monthly review, both with charts.

## Quick start

```bash
# 1. Install (uv recommended)
uv sync
# or:  pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# edit .env — put your FRED API key in
# edit config/funds.yaml — list the ILAS funds your clients hold

# 3. Run
uv run manulife fetch          # pull latest prices & macro data
uv run manulife analyze        # compute metrics into the DB
uv run manulife report weekly  # build HTML report in data/reports/
uv run manulife report monthly
```

The reports land in `data/reports/YYYY-MM-DD-{weekly,monthly}.html`.

## Project layout

```
config/             funds.yaml (ILAS universe) + settings.yaml
src/manulife_analyzer/
  data/             fetchers — manulife, yahoo, fred, world_bank
  storage/          SQLite persistence
  analysis/         metrics, momentum, macro signals, fund screener
  reports/          Jinja2 templates + chart helpers + report builder
  cli.py            `manulife fetch | analyze | report ...`
tests/              unit tests with mocked HTTP / sample data
data/               gitignored — raw, processed, reports, DB
```

## Configuration

### `config/funds.yaml`

List the Manulife-linked funds you want to track. Most Manulife ILAS products
in Hong Kong invest in a curated set of mutual funds; each has an ISIN you can
find on the product PIB.

```yaml
funds:
  - code: MGS-USEQ
    isin: HK0000056226
    name: Manulife Global Fund - US Equity
    category: equity
    region: us
    benchmark: ^GSPC          # Yahoo ticker for the comparison index
    manulife_url: https://www.manulife.com.hk/...   # optional, for scraper
```

### `config/settings.yaml`

Picks data sources, lookback windows, and report parameters. Defaults are sane.

## Data sources

| Source | What | Notes |
|---|---|---|
| Manulife HK fund-price page | Daily NAV per linked fund | Public page; scraper is rate-limited and honours robots.txt where present. Replace with the official CSV/PDF feed if your relationship gives you one. |
| FRED | US rates, CPI, unemployment, yield curve | Free, requires API key |
| Yahoo Finance (`yfinance`) | Index/ETF prices for benchmarks | Free, no key |
| World Bank | Global GDP and macro series | Free, no key |

## Compliance & disclaimers

- **Scraping**: only public, non-account pages. The fetcher sets a contact User-Agent,
  rate-limits requests, and caches responses for 24h. If Manulife provides an
  official data feed under your distributor agreement, switch to it — see
  `src/manulife_analyzer/data/manulife.py`.
- **Advice**: this system outputs *observations and signals* (e.g. "30-day
  volatility on Asian equity funds rose to 18%, vs 12% trailing"). It does
  **not** generate personalised buy/sell instructions for any specific client.
  In HK/SG/MO a licensed person must review and sign off on any recommendation
  given to a client.
- **Past performance** does not guarantee future results. Every report carries
  a disclaimer footer.

## Development

```bash
uv run pytest                  # unit tests (no network needed; uses fixtures)
uv run ruff check src tests
```

Tests stub all HTTP via `respx` so they pass without internet access.

## Roadmap (not in v1)

- Client-level portfolio attribution (requires holdings input)
- Notion / email delivery of reports
- Scheduled runs (GitHub Actions or cron)
- Backtesting of signal rules
