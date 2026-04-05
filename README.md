# polymarket-sports-mm

Sports market making bot for [Polymarket](https://polymarket.com) liquidity rewards.

Quotes pre-game and live sports markets on both sides of the book, optimized for the quadratic reward function `S(v,s) = ((v-s)/v)²`.

## How it works

Polymarket distributes $5M+/month to market makers who post resting limit orders on sports markets. Orders are scored every minute based on:

- **Tightness**: closer to midpoint → quadratically higher score
- **Two-sided**: quoting both sides gives 3x vs single-sided
- **Size**: linear with quantity
- **Uptime**: every minute sample counts

This bot places symmetric quotes around the adjusted midpoint (maximizing score) and skews sizes to manage inventory.

## Quick start

```bash
pip install -e ".[dev]"

# Discover available sports events
sfmm discover

# Dry run (no real orders)
sfmm run --dry-run

# Real quoting (requires Polymarket credentials)
export POLYMARKET_PRIVATE_KEY=0x...
export POLYMARKET_API_KEY=...
export POLYMARKET_API_SECRET=...
export POLYMARKET_API_PASSPHRASE=...
sfmm run --mode pre
```

## Architecture

```
sfmm discover → Gamma API → find sports events + token IDs
sfmm run      → poll orderbook → compute quotes → place via py-clob-client

Quote engine:
  price = midpoint ± 1 tick  (maximize score)
  size  = skewed by view + inventory mean-reversion  (manage risk)

Risk:
  circuit breaker (detect midpoint jumps → pull quotes → cooldown)
  position limits, daily loss cap
```

## Configuration

Copy `config.example.toml` and set env vars from `.env.example`.

## License

MIT
