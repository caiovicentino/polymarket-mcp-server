# Security Policy

This project holds a wallet private key and can place real orders with real
money. Treat any bug that affects key handling, order construction, or the
safety limits as a security issue.

## Supported Versions

Only the latest release on `main` receives security fixes.

| Version | Supported |
| ------- | --------- |
| latest `main` | ✅ |
| older tags | ❌ |

## Reporting a Vulnerability

**Do not open a public issue for a vulnerability.**

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/caiovicentino/polymarket-mcp-server/security/advisories/new).

Please include:

- What the vulnerability allows an attacker (or a mistaken LLM call) to do
- Steps to reproduce, ideally with the tool name and arguments
- The version or commit you tested
- Any suggested fix

You can expect an initial response within 7 days. Please give us a reasonable
window to ship a fix before disclosing publicly.

## In Scope

- Private key or API credential leaking into logs, error messages, tool
  output, or the web dashboard
- Bypassing the configured safety limits (`MAX_ORDER_SIZE_USD`,
  `MAX_TOTAL_EXPOSURE_USD`, `MAX_POSITION_SIZE_PER_MARKET`,
  `REQUIRE_CONFIRMATION_ABOVE_USD`)
- Order construction that trades a different market, outcome, side, or size
  than requested
- Authentication or signing flaws in `src/polymarket_mcp/auth/`
- Prompt injection through market data (titles, descriptions, resolution
  sources) that causes an unintended trade
- Remote code execution, SSRF, or path traversal via the web dashboard

## Out of Scope

- Trading losses from your own strategy or market movement
- Polymarket API outages, rate limiting, or upstream changes
- Vulnerabilities in dependencies without a demonstrated impact here — report
  those upstream
- Missing hardening on a dashboard you deliberately exposed to the internet
  (it is intended for `localhost`)

## Operational Guidance

The safeguards below are your responsibility as an operator; they are not
enforced by this project.

- **Use a dedicated wallet.** Fund it only with what you are willing to trade.
  Never point this server at a wallet holding significant assets.
- **Keep the private key out of the repository.** Use `.env` (already
  gitignored) or your OS keychain. Never paste it into an issue or a chat.
- **Do not expose the web dashboard.** It has no authentication and is meant to
  bind to `localhost` only.
- **Set safety limits before enabling trading.** The defaults are examples, not
  recommendations.
- **Remember the LLM is in the loop.** An agent can misread a market or be
  manipulated by text inside market data. Keep
  `REQUIRE_CONFIRMATION_ABOVE_USD` low and review what it proposes.
- **Run read-only when exploring.** Omit the API credentials to get the 25
  public tools with no trading capability.
