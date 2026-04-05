# polymarket-sports-mm

Sports market making bot for [Polymarket](https://polymarket.com) liquidity rewards. Part of the [SimpleFunctions](https://simplefunctions.dev) prediction market toolkit.

Polymarket pays **$5M+/month** to market makers who post resting limit orders on sports markets. This bot quotes both sides of the book — pre-game and live — to capture those rewards.

> **New to prediction markets?** [SimpleFunctions](https://simplefunctions.dev) provides real-time market intelligence, edge detection, and execution tools across Polymarket and Kalshi. This bot is one piece of that stack — focused specifically on sports liquidity rewards.

## The math

Every minute, Polymarket samples your resting orders and scores them:

```
S(v, s) = ((v - s) / v)²

v = max qualifying spread (set per market, typically 3-5 cents)
s = your order's distance from midpoint
```

This is quadratic. Being 2x tighter = 4x the score:

```
Distance from mid    Score
0 cents (at mid)     1.000
1 cent               0.444
2 cents              0.111
3 cents (at max)     0.000
```

Two-sided quoting (bid + ask) scores **3x** vs single-sided. The bot always quotes both sides.

## Install

```bash
pip install sfmm
```

Or from source:

```bash
git clone https://github.com/spfunctions/polymarket-sports-mm.git
cd polymarket-sports-mm
pip install -e .
```

## Usage

### Discover markets

No credentials needed. Scans Polymarket for active sports events:

```bash
$ sfmm discover

                     Sports Events (376 found)
┌────────────┬──────────────────────────────────┬─────┬──────────┐
│ Sport      │ Event                            │ Mid │ Volume   │
├────────────┼──────────────────────────────────┼─────┼──────────┤
│ soccer     │ 2026 FIFA World Cup Winner       │0.16 │ $467,000 │
│ basketball │ 2026 NBA Champion                │0.36 │  $33,200 │
│ hockey     │ 2026 NHL Stanley Cup Champion    │0.12 │   $2,745 │
│ soccer     │ UEFA Champions League Winner     │0.10 │   $5,557 │
│ basketball │ NBA MVP                          │0.27 │   $4,700 │
│ ...        │                                  │     │          │
└────────────┴──────────────────────────────────┴─────┴──────────┘
```

### Dry run

No credentials needed. Fetches real orderbooks, computes real quotes, logs what it would place:

```bash
$ sfmm run --dry-run

DRY RUN — no orders will be placed

PRE 2026 FIFA World Cup Winner (58 markets)
PRE 2026 NBA Champion (20 markets)

[DRY] place BUY 100 @ 0.15 on Spain token
[DRY] place SELL 100 @ 0.17 on Spain token
  Will Spain win the 2026 FIFA W: bid 0.15x100 ask 0.17x100 (mid=0.157)

[DRY] place BUY 100 @ 0.36 on OKC Thunder token
[DRY] place SELL 100 @ 0.39 on OKC Thunder token
  Will the Oklahoma City Thunder: bid 0.36x100 ask 0.39x100 (mid=0.375)
```

### Real quoting

Requires Polymarket CLOB credentials ([register here](https://docs.polymarket.com)):

```bash
export POLYMARKET_PRIVATE_KEY=0x...
export POLYMARKET_API_KEY=...
export POLYMARKET_API_SECRET=...
export POLYMARKET_API_PASSPHRASE=...

# Pre-game only
sfmm run --mode pre

# Pre-game + live (auto-transitions at kickoff)
sfmm run

# Specific market
sfmm run --market <condition_id>
```

## How the bot quotes

The core insight: **prices for score, sizes for view.**

```
Bid price = midpoint - 1 tick     (maximizes quadratic score)
Ask price = midpoint + 1 tick     (symmetric = balanced Q_min)

Bid size  = base × (1 + skew)    (skew > 0 if bullish)
Ask size  = base × (1 - skew)    (skew blends view + inventory mean-reversion)
```

Moving prices away from midpoint to express a view kills your score (quadratic penalty). Instead, keep prices tight and adjust the size ratio.

## Architecture

```
sfmm discover
  │
  │  Polymarket Gamma API
  │  → find sports events, extract token IDs
  ▼
sfmm run
  │
  ├─ Pre-game engine (poll every 5s)
  │   ├─ Fetch orderbook (CLOB API)
  │   ├─ Compute adjusted midpoint
  │   ├─ Fair value = midpoint or external odds blend
  │   ├─ Quote engine → optimal bid/ask price & size
  │   └─ Cancel-and-replace via py-clob-client
  │
  ├─ Live engine (poll every 1s)
  │   ├─ Circuit breaker: midpoint jump > threshold → pull quotes
  │   ├─ Cooldown → re-read mid → requote
  │   └─ Symmetric only (no view skew — survival mode)
  │
  ├─ Risk manager
  │   ├─ Position limits, exposure cap, daily loss limit
  │   └─ Inventory mean-reversion via size skew
  │
  └─ SimpleFunctions bridge (optional)
      ├─ Reports fills to SF intent API
      ├─ Telegram notifications via SF heartbeat
      └─ Cross-references with SF edge detection
```

## SimpleFunctions integration

This bot works standalone, but it's designed to plug into the [SimpleFunctions](https://simplefunctions.dev) ecosystem for enhanced intelligence and execution tracking.

### Market intelligence

Use the [SimpleFunctions Python SDK](https://github.com/spfunctions/simplefunctions-python) (`pip install simplefunctions-ai`) to enhance fair value:

```python
import simplefunctions as sf

# Cross-venue scan — find the same event on Kalshi + Polymarket
markets = sf.scan("NBA Champion 2026")

# Get real-time world context that might affect the game
world = sf.world()

# Query with natural language
answer = sf.query("What are the odds implications of the Lakers injury report?")
```

### Execution tracking

Set `SF_API_KEY` to automatically report every game as an [intent](https://simplefunctions.dev/docs) — fills, P&L, and lifecycle are tracked and pushed to Telegram:

```bash
export SF_API_KEY=sf_live_...

# Bot creates intents, records fills, closes on game end
sfmm run --mode pre
```

Then monitor from the [SF CLI](https://github.com/spfunctions/simplefunctions-cli):

```bash
# See all active market making intents
sf intent list --source agent --venue polymarket

# Check positions and P&L
sf positions
```

### Edge-informed quoting

The bot defaults to quoting symmetrically around midpoint (pure reward farming). But with SF, you can lean into edges:

```bash
# SF detects a mispricing on the Lakers game
sf edges
  Lakers YES: market 42¢, SF-implied 51¢, edge +9¢

# The bot picks this up and skews sizes:
# bid_size = 150 (buy more — we think it's cheap)
# ask_size = 80  (sell less)
# Prices stay at mid ± 1 tick (score unchanged)
```

## Reward pools (April 2026)

| League | Total/game | Pre | Live |
|--------|-----------|-----|------|
| Champions League QFs | $24,000 | $6,750 | $17,250 |
| English Premier League | $10,000 | $2,800 | $7,200 |
| NBA | $7,700 | $2,150 | $5,550 |
| CS2 A-tier | $5,500 | $1,550 | $3,950 |
| IPL Cricket | $4,500 | $1,250 | $3,250 |
| La Liga / Serie A | $3,300 | $900 | $2,400 |
| MLB | $1,650 | $465 | $1,185 |
| NHL | $1,500 | $400 | $1,100 |

Full list: [Polymarket docs](https://docs.polymarket.com/market-makers/liquidity-rewards)

## Configuration

Copy `config.example.toml`:

```toml
[quoting]
spread_ticks = 1                # ticks from midpoint
min_size_multiplier = 2.0       # quote min_incentive_size * this
max_position_per_market = 1000
max_total_exposure_usd = 5000

[risk]
daily_loss_limit_usd = 500
circuit_cooldown_sec = 10
inventory_half_life = 500

[feeds]
poll_interval_pre = 5.0
poll_interval_live = 1.0
```

Environment variables (`.env.example`):

```bash
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=
SF_API_KEY=              # optional — SimpleFunctions intent reporting
ODDS_API_KEY=            # optional — external odds for fair value
```

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v -p no:asyncio
```

47 tests covering scoring (verified against [Polymarket docs worked example](https://docs.polymarket.com/market-makers/liquidity-rewards#worked-example)), quote engine, and risk logic.

## Roadmap

- [x] Core scoring (S(v,s), Q_min, adjusted midpoint)
- [x] Quote engine (prices for score, sizes for view)
- [x] Pre-game engine
- [x] Live engine with circuit breaker
- [x] Market discovery (376 events found)
- [x] Dry-run mode
- [x] SimpleFunctions intent bridge
- [ ] SF edge-informed size skew
- [ ] External odds feed (Pinnacle/Betfair fair value anchor)
- [ ] Sport-specific probability models (Dixon-Coles for soccer)
- [ ] Rich terminal dashboard
- [ ] Backtest against historical orderbook data
- [ ] WebSocket feeds (replace polling)

## Related

- **[SimpleFunctions](https://simplefunctions.dev)** — prediction market intelligence platform
- **[simplefunctions-ai](https://pypi.org/project/simplefunctions-ai/)** — Python SDK for real-time market data (world state, edges, scanning)
- **[simplefunctions-cli](https://github.com/spfunctions/simplefunctions-cli)** — CLI for thesis-based trading, intents, and 24/7 monitoring
- **[Polymarket Liquidity Rewards](https://docs.polymarket.com/market-makers/liquidity-rewards)** — official reward program docs

## License

MIT
