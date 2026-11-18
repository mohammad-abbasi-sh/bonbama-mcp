# bonbama-mcp 🇮🇷

mcp-name: io.github.mohammad-abbasi-sh/bonbama-mcp

Unofficial **read-only** MCP server for [bonbama.ir](https://bonbama.ir) — Gorgan's discount platform: local businesses, discount codes and campaigns, business categories, and magazine articles. All data is read **live** from bonbama.ir public pages at call time — nothing is hardcoded.

> Not affiliated with Bonbama. Built for the Bazaar MCP Hub submission — see [DEPLOY.md](DEPLOY.md) for hosting.

## For AI agents

**Local (stdio)** — add to your MCP client config:

```json
{
  "mcpServers": {
    "bonbama": {
      "command": "uvx",
      "args": ["bonbama-mcp"]
    }
  }
}
```

Or run locally: `python -m bonbama_mcp.server` (needs `mcp<2`, `httpx`, `uvicorn`).

**Hosted (streamable HTTP)** — for clients that connect to a remote MCP server:

```
https://api.bonbama.ir/mcp
```

MCP endpoint is `/mcp` (streamable HTTP, stateless — no session affinity needed); liveness probe at `/health`. Hosting guide: [DEPLOY.md](DEPLOY.md).

## Tools

| Tool | Description |
|------|-------------|
| `bb_search_businesses` | Search businesses by keyword and/or category slug — `query`, `category`, `limit` |
| `bb_get_business` | Full details for one business — `slug` (e.g. `testino`, `takchh`): description, city, address, rating, category, ACTIVE campaigns with discount + expiry, and any literal discount codes published on the page |
| `bb_list_categories` | All business categories with Persian names + business/campaign counts |
| `bb_search_discounts` | Search ACTIVE discount campaigns site-wide — `query` (empty = popular campaigns) |
| `bb_search_articles` | Search the Bonbama magazine (guides, best-of-Gorgan lists) — `query` |
| `bb_health` | Check whether bonbama.ir is reachable right now |

Example output (`bb_get_business` / `takchh`, trimmed):

```json
{"name": "طاقچه | خرید کتاب الکترونیکی و صوتی و اشتراک بی‌نهایت",
 "city": "تهران", "campaign_count": 5,
 "campaigns": [{"title": "۵۰٪ تخفیف اولین خرید طاقچه — فقط از طریق بن‌باما",
   "discount": "50%", "valid_through": "2027-01-20"}],
 "codes": [{"code": "OFF50", "note": "۵۰٪ تخفیف اولین خرید"}]}
```

Notes:
- Campaigns, codes, prices and expiries are read live from the page on every call — they change; always report `fetched_at` and tell the user to verify on the business page before buying.
- Literal codes (e.g. `OFF50`) come from the business page's own text. Some campaigns instead need the user to press «دریافت کد» on bonbama.ir (free, needs a free account) to generate their personal code/QR — those codes are per-user and are never returned here.
- Data sources: bonbama.ir sitemaps + public search, business, category and article pages — no key, no login, read-only. This server never writes anything to bonbama.ir.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/python -m pytest tests/ -q          # 29 offline + 7 live tests
.venv/bin/python -m pytest tests/test_bonbama.py -q   # offline only
```

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/) — free for personal and non-commercial use; commercial use needs a separate license.

Built by [Mohammad Abbasi](https://github.com/mohammad-abbasi-sh) — [Almanibama](https://almanibama.ir) · [mabbasi.ir](https://mabbasi.ir)
