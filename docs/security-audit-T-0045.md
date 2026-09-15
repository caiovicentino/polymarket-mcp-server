# Security Audit — T-0045: Adversarial Review of the Safety Layer

**Repo:** polymarket-mcp-server · **Baseline:** main `5829c7f` · **Date:** 2026-09-15
**Trigger:** issue #41 — an external security researcher offered a stress-test of the
"enterprise-grade safety" claims (README:10/93, SECURITY.md:37-39), citing
deny/allow-list edge cases (regex quote-splitting) and tool-call scope as candidate
attack classes. This audit answers by running the same exercise first, with every
candidate vector resolved by **machine evidence** (an offline reproduction), not by
opinion. Artifacts: `tests/test_safety_adversarial.py` (executable evidence) and this
document. Zero network, zero code changes — findings feed curated follow-up fixes.

---

## 1. Scope & Method

**What was audited (offline, layer-boundary):**

| Layer | Files |
| --- | --- |
| Numeric limits | `src/polymarket_mcp/utils/safety_limits.py` (validate_order :97-189, confirmation gate :215-236) |
| Order entry + multi-leg execution | `src/polymarket_mcp/tools/trading.py` (create_limit_order :103-296, create_batch_orders :374-461, execute_smart_trade :893-1055, rebalance_position :1057-1191, resolve_token_id :25-77, _convert_positions :1195-1217) |
| Configuration edges | `src/polymarket_mcp/config.py` (safety-limit fields :63-100, DEMO_MODE :25-28) |
| Tool-call scope / routing | `src/polymarket_mcp/server.py` (list_tools :110-144, call_tool :243-343, initialize_server :346-444) |
| Credential wiring | `src/polymarket_mcp/auth/client.py` (constructor :36-90, create_api_credentials :129-166, has_api_credentials :471-473) |

**Method.** Every candidate vector ends in exactly one of three states:

- **CONFIRMED** — an `xfail(strict=True)` test whose body asserts the *safe*
  behavior; the assertion fails against the current code, which *is* the proof of
  the bypass. If the code is later fixed, the test XPASSes and the suite turns RED,
  forcing the suite to be updated in the same change (anti-fabrication by design).
- **REFUTED** — a positive test pinning the safe behavior actually observed.
- **DESIGN/OBSERVATION** — a non-correctable-here product decision, labeled
  "not machine-verified" below, never asserted as a bug.

Hermeticity is executable: the suite passes under `env -i PATH=/usr/bin:/bin
PYTHONPATH=src HOME=/tmp` (empty environment) — no credentials, no network, no
timing dependence. All client I/O goes through duck-typed recording fakes; calling
an unfaked endpoint raises `AttributeError` loudly instead of silently reaching the
network.

**What is NOT provable offline** (declared honestly, never asserted as fact): the
behavior of the live CLOB/Data API (formats of real responses, acceptance of
demo-key orders), the MCP transport's JSON parsing policy, and multi-process
scheduling of tool calls. Where a finding depends on one of these, the precondition
is named in the finding.

---

## 2. Claims vs Code

| Claim (source) | Verdict | Evidence |
| --- | --- | --- |
| README:10 — "45 comprehensive tools" | **ACCURATE** | Definitions sum to 45 = 8 discovery + 10 analysis + 12 trading + 8 portfolio + 7 realtime (`test_readme_tool_count_claim_matches_definitions`); every defined name is dispatchable through `call_tool` (`test_all_defined_tools_are_routed`) |
| README:93 — "Enterprise-Grade Safety & Risk Management" | **OVERSTATED as absolute** | The safety layer exists and rejects the ordinary cases (T-0032/T-0041/T-0042 pinned them), but this audit found machine-verified bypasses: SEC-ADVR-A1 (NaN), A2 (id-format blindness), B1 (in-flight ratchet), B2 (TOCTOU), D1 (config silently disables limits). Accurate if read as "safety features exist", inaccurate if read as "no bypass exists" |
| README:417-432 — default safety limits ($1,000 / $5,000 / $2,000 / liquidity / spread / $500 confirmation) | **ACCURATE defaults, no guardrails on the knobs** | Defaults match config.py:63-100; but the fields accept `<= 0` and `inf` values that silently disable the checks (SEC-ADVR-D1) |
| SECURITY.md:37-39 — bypassing the configured limits is in scope | **CONFIRMED RELEVANT** | Five machine-verified limit bypasses found (A1, A2, B1, B2, D1) — exactly the class SECURITY.md declares in scope |
| SECURITY.md:41-42 — order construction trading a different market/outcome/side/size than requested | **REFUTED for the tested surfaces** | side allow-list is exact equality (A3 tests), outcome resolution is exact casefold with strip (trading.py:50-54), order kwargs pass through verbatim (T-0041) |
| SECURITY.md:43-44 — prompt injection through market data | **OUT OF SCOPE here** | Mitigation boundary is the LLM/model layer, not this codebase; see §6 |
| config.py:25-28 — DEMO_MODE "Run in demo mode without real wallet (read-only, no trading)" | **REFUTED as enforced behavior** | No line of `server.py` or `trading.py` consults `DEMO_MODE` (grep evidence in §6); with `confirm=True` a demo-config order proceeds (SEC-ADVR-C1). The description is a claim the code does not enforce |
| server.py:438-439 — "Mode: READ-ONLY (no API credentials)", "25 total" | **ACCURATE** | `test_list_tools_preauth_excludes_trading_and_portfolio`: pre-auth surface is exactly discovery+analysis+realtime = 25 |

---

## 3. Findings

Severity: P0 critical / P1 high / P2 medium / P3 low.

### SEC-ADVR-A1 — NaN order size bypasses every limit and reaches post_order — **P1, CONFIRMED**

- **File:line:** `tools/trading.py:143` (`if size <= 0:` — False for NaN),
  `utils/safety_limits.py:117,139,164` (`value > limit` — always False for NaN),
  `utils/safety_limits.py:236` (confirmation threshold — skipped for NaN).
- **Repro (executable):** `test_nan_size_bypasses_all_limits_and_reaches_post_order`
  (xfail strict) — a `create_limit_order` with `size=float('nan')` posts to the
  exchange with `size=nan` shares while every cap and the confirmation gate are
  skipped. By contrast, `size=inf` IS caught (inf > limit is True) — the bypass is
  NaN-specific.
- **Impact:** an order of unbounded USD value (NaN × price is NaN) passes
  order-size, total-exposure, per-market caps and the confirmation gate, and is
  forwarded to the exchange client.
- **Preconditions (honest):** the proof covers the tool-layer frontier. The MCP
  transport may deliver NaN because Python's `json.loads` accepts `NaN`/`Infinity`
  literals by default (pinned in `test_nan_is_not_normalizable_by_float_helpers`);
  whether the server's JSON-RPC parser in the installed transport rejects them is
  **not machine-verified** here. If a strict parser drops NaN upstream, the vector
  narrows to any caller of `create_limit_order` (programmatic use) and to NaN
  arriving through upstream market data.
- **Recommendation:** reject non-finite sizes at entry (`size <= 0 or not
  math.isfinite(size)`), and make the limit comparisons NaN-safe (`not (value <=
  limit)` rejects NaN) or explicitly validate finiteness in `validate_order`.

### SEC-ADVR-A2 — Per-market cap is blind to market-id format divergence — **P2, CONFIRMED (mechanism)**

- **File:line:** `utils/safety_limits.py:147-150` — positions are filtered by
  exact string equality `p.market_id == order.market_id`; no normalization.
- **Repro (executable):** `test_per_market_cap_bypassed_by_position_market_id_format_mismatch`
  (xfail strict) — with a position of $450 in the same logical market under a
  different id format, a $100 BUY is accepted where the matching format rejects it
  (market exposure 550 > 500 cap).
- **Impact:** the per-market position cap can be bypassed whenever position ids
  and order market ids diverge in format, concentrating exposure beyond the cap.
- **Preconditions:** the matching semantics are machine-verified at the unit seam.
  Whether the live Data API returns `market` values in the same format the caller
  passes is **not provable offline**. Corroborating evidence that two id formats
  circulate: `_convert_positions` maps `pos_data.get('market')` verbatim
  (trading.py:1206) while `rebalance_position` matches EITHER `market` OR
  `condition_id` (trading.py:1087) — the codebase itself acknowledges both fields.
- **Already covered elsewhere (contrast):** `tests/test_safety_limits.py:288`
  pins the cap WITH matching formats; `tests/test_safety_limits.py:311` pins the
  skip when `market_id` is falsy. The format-divergence case was NOT pinned before.
- **Recommendation:** match positions by both `market` and `condition_id`
  (mirroring rebalance_position:1087), or by the token_id set of the market.

### SEC-ADVR-B1 — Multi-leg orders ratchet exposure past the total cap — **P1, CONFIRMED**

- **File:line:** `tools/trading.py:404-415` (batch loop), `:964-1003` (smart-trade
  split legs), `:1148` (rebalance — same single-order validation); validation reads
  only `get_positions()` (trading.py:188) — FILLED positions. A resting (unfilled)
  limit order never appears there.
- **Repro (executable):** `test_batch_orders_ratchet_exposure_past_total_cap` and
  `test_smart_trade_split_orders_ratchet_exposure_past_cap` (both xfail strict) —
  two legs of $800 (cap $1,000/order, $1,000 total) both post; combined exposure
  $1,600 > cap.
- **Impact:** N orders each individually under `MAX_ORDER_SIZE_USD` stack total
  exposure far above `MAX_TOTAL_EXPOSURE_USD` — the cap is enforced per-order, not
  per-plan.
- **Preconditions:** the fake models positions that do not include in-flight
  orders — matching real semantics for unfilled resting orders. A fill between
  legs would make the next validation see the position (if the Data API had
  propagated it); with fast sequential submission or resting orders, the ratchet
  holds.
- **Recommendation:** track in-flight (posted-but-unfilled) notional per session
  and include it in `validate_order`'s exposure input, or validate the whole
  plan/batch before executing any leg.

### SEC-ADVR-B2 — Concurrent tool calls validate the same stale exposure snapshot (TOCTOU) — **P1, CONFIRMED**

- **File:line:** `tools/trading.py:188` (per-call `get_positions()`); no lock or
  serialization exists in the module (grep evidence: no `asyncio.Lock` in
  `tools/trading.py`).
- **Repro (executable):** `test_concurrent_orders_both_validate_stale_exposure_snapshot`
  (xfail strict, deterministic — an `asyncio.Event`-coordinated fake guarantees
  both `get_positions` calls complete before any `post_order`; no sleeps) — both
  concurrent orders post; combined exposure $1,600 > cap $1,000.
- **Impact:** same as B1, but exploitable even with correct per-call semantics —
  two simultaneous calls each see pre-trade exposure.
- **Preconditions:** the MCP client may parallelize tool calls; the server does
  not impose serialization (**not machine-verified offline** — scheduling is
  upstream).
- **Recommendation:** a per-process asyncio lock around the validate-then-post
  section, or an atomic reserve-commit exposure ledger.

### SEC-ADVR-B3 — Confirmation gate is consultive (caller-controlled) — **DESIGN/OBSERVATION, not machine-verified**

The gate is strict about *when* it fires (T-0041 pinned: one cent above the
threshold → held until `confirm=True`), but the decision to confirm belongs to the
same caller (the LLM) that issued the order; there is no out-of-band approval
channel. This is a product decision, not a code defect in this slice: any fix
(approval token issued by the dashboard, second-channel confirmation for
high-value orders) is a design change. **No test created** — the semantics are
already pinned by T-0041 (`tests/test_trading_offline.py:184-216`).

### SEC-ADVR-C1 — DEMO_MODE does not gate trading ("read-only, no trading" is unenforced) — **P1, CONFIRMED (claims-vs-code)**

- **File:line:** `config.py:25-28` (the claim); the flag is consulted ONLY inside
  `config.py` for credential substitution (:132-181). `grep -rn "DEMO_MODE"
  src/polymarket_mcp/` → no hit outside config.py. `server.py:380-398` attempts L2
  credential auto-creation with **no DEMO_MODE check**; `server.py:408-418`
  initializes trading tools whenever the *client* reports credentials
  (`client.py:471-473`); `create_api_credentials` (client.py:129-166) auto-creates
  L2 creds.
- **Repro (executable):**
  - Link A (refuted-safe): `test_demo_config_reports_no_credentials` — a
    DEMO_MODE config with no L2 vars reports `has_api_credentials()=False`, which
    is precisely what drives server.py:381 into the auto-creation branch.
  - Link B (refuted-safe): `test_real_client_accepts_demo_key_offline` — the real
    `PolymarketClient` constructs offline with the public demo key; the order
    signer derives from it; chain defaults to mainnet (137).
  - Bypass (confirmed): `test_demo_mode_config_still_places_orders_with_confirm`
    (xfail strict) — the tool layer accepts the demo config and, with
    `confirm=True`, places the order. The only guard is the consultive gate
    (SEC-ADVR-B3).
- **Impact:** an operator setting `DEMO_MODE=true` for read-only safety gets full
  trading tools whenever L2 credentials are present (explicitly configured) or
  creatable (auto-created over the network). Orders would be signed with the
  public demo key (funds = 0 by definition), or with a credentials/key mismatch
  whose server-side behavior is unknown.
- **Preconditions (NOT machine-verified):** (a) `create_api_key` succeeding from
  the demo key over the network; (b) the CLOB accepting orders signed by the demo
  key / mismatched creds. Both are production-network steps, deliberately out of
  reach of this offline audit.
- **Recommendation:** gate trading-tool initialization (server.py:409) — and/or
  `create_limit_order` entry — on `not config.DEMO_MODE`, and reword
  config.py:25-28 to state the actual guarantee.

### SEC-ADVR-C2 — Router fail-closed everywhere tested; tool-count claims accurate — **P3, mostly REFUTED**

- **Refuted (safe behavior pinned):**
  - Unknown tool → JSON error result, no crash, no path leak
    (`test_unknown_tool_returns_fail_closed_error`, server.py:318/:330-343).
  - Trading route without initialized tools → "Unknown tool" fail-closed
    (`test_trading_route_fail_closed_without_tools`, server.py:292/:327-328).
  - Portfolio route with pre-init `config=None` → handler-internal failure
    returned as text, no crash, no path leak
    (`test_portfolio_route_fails_closed_preinit`, portfolio.py:209-212).
  - Pre-auth `list_tools()` excludes all trading/portfolio tools, surface = 25
    (`test_list_tools_preauth_excludes_trading_and_portfolio`, server.py:130-139).
  - Tool counts match README:10/server.py:436 exactly (45 = 8+10+12+8+7) and every
    defined tool is routed (`test_readme_tool_count_claim_matches_definitions`,
    `test_all_defined_tools_are_routed`).
- **Observation (P3, not machine-verified further offline):** the portfolio route
  (server.py:270-280) sits BEFORE the `elif trading_tools:` gate (:292) and is
  reachable regardless of credentials; its live path performs direct data-api HTTP
  calls (portfolio.py:86-97). The data is public per-address market data, so this
  is a hardening/polish note (error shape, gate symmetry), not an access-control
  bypass.
- **Observation (P3):** the `error_result` echoes the caller's `arguments`
  (server.py:336) — reflected input, not a new information leak; documented so
  future reviewers do not re-flag it.

### SEC-ADVR-D1 — Safety-limit config accepts values that silently disable the checks — **P2, CONFIRMED (config level)**

- **File:line:** `config.py:63-100` — `MAX_ORDER_SIZE_USD`,
  `MAX_TOTAL_EXPOSURE_USD`, `MAX_POSITION_SIZE_PER_MARKET`,
  `MIN_LIQUIDITY_REQUIRED`, `REQUIRE_CONFIRMATION_ABOVE_USD` have no numeric
  constraints; the only constrained field is `MAX_SPREAD_TOLERANCE` (0-1,
  config.py:183-188).
- **Classification (machine-verified):**
  - FAIL-OPEN: `MIN_LIQUIDITY_REQUIRED <= 0` disables the floor silently
    (safety_limits.py:171 — `<` never fires; `test_nonpositive_min_liquidity_disables_liquidity_floor`);
    infinite caps disable order-size/exposure limits
    (`test_infinite_order_cap_disables_size_limit`).
  - FAIL-CLOSED (safe direction): negative size/exposure/market caps reject
    everything (`test_negative_max_order_size_fails_closed`);
    `REQUIRE_CONFIRMATION_ABOVE_USD <= 0` gates every order
    (`test_nonpositive_confirmation_threshold_gates_all_orders`).
- **Repro of the gap (executable):** `test_config_accepts_limits_that_disable_safety`
  (xfail strict) — `PolymarketConfig(DEMO_MODE=True, MIN_LIQUIDITY_REQUIRED=-1.0)`
  constructs fine; the safe behavior (ValidationError) is asserted and fails.
- **Impact:** a mistyped `.env` (`MIN_LIQUIDITY_REQUIRED=0` or `inf`) silently
  removes a documented safety floor with no warning — the operator believes the
  limit is active (README:417-432) while it is off.
- **Recommendation:** `Field(ge=...)` constraints (or a validator) rejecting
  non-positive and non-finite values for all five limit fields.

### SEC-ADVR-D2 — Quote-splitting / regex allow-list class: **N/A with evidence**

- **Evidence 1:** `grep -rn "re\.compile\|re\.match\|re\.search\|re\.fullmatch"
  src/polymarket_mcp/` → **0 matches** (exit 1). There is no regex-based
  input filtering anywhere in the package for the class to attack. The tripwire
  `test_no_regex_input_validation_in_safety_layer` pins this and will fail loudly
  if regex validation is ever added to the safety modules.
- **Evidence 2:** the allow-lists that DO exist are exact comparisons: side =
  exact equality after `.upper()` (trading.py:146-148; A3 tests reject padded,
  spaced, and Cyrillic-homoglyph inputs); outcome resolution = strip + exact
  casefold (trading.py:50-54; prefix/substring/spaced inputs rejected —
  `test_token_id_matching_is_exact_not_prefix`, `test_token_id_strips_then_exact_matches`).
- **Surface note:** `token_id` is an opaque pass-through string; a crafted value
  travels into API request parameters, not into code paths — treated as upstream
  API surface, not a local vector.

---

## 4. Mutation Evidence

Every positive (refuted) test was proven able to fail via the P-0020 shadow
pattern: the module under test is extracted to a temp-dir package tree
(symlinked except the mutated module — a real file), the UNTOUCHED suite runs with
`PYTHONPATH=shadow:src`, and each mutation must fail exactly its predicted tests
(L-0082: replacement asserted applied once; L-0112: per-test prediction, never
aggregate inference). Shadowing proven via `module.__file__` → temp path, real
file (not symlink). Baseline: untouched suite green (19 passed + 7 xfailed).

| Mutation | Module | Change (find → replace) | Predicted failures | Observed |
| --- | --- | --- | --- | --- |
| M1-side-guard | tools/trading.py | `if side not in ['BUY', 'SELL']:` → `if False:` | 3 (A3 padded/spaced/cyrillic) | **3 MATCH** |
| M2-token-substring | tools/trading.py | `label.casefold() == wanted` → `label.casefold() in wanted` | 1 (token prefix) | **1 MATCH** |
| M3-regex-injected | utils/safety_limits.py | inject `re.compile("SEC-ADVR-TRIPWIRE")` | 1 (tripwire) | **1 MATCH** |
| M4-credcheck-true | config.py | `return all([` → `return True or all([` | 1 (demo credcheck) | **1 MATCH** |
| M5-server-except | server.py | `except Exception as e:` → `except KeyboardInterrupt as e:` (call_tool block) | 2 (unknown-tool, trading-without-tools) | **2 MATCH** |
| M6-size-guard | utils/safety_limits.py | `if order_value_usd > self.max_order_size_usd:` → `if False:` | 1 (negative-max fail-closed) | **1 MATCH** |

Runner summary: `SUMMARY: ALL-MATCH`, exit 0. The xfails (A1, A2, B1 ×2, B2, C1,
D1-config) prove themselves: they fail against the real code with strict=True, so
a fix that lands without updating the suite turns it RED.

---

## 5. Already Covered (cross-references — no duplication in this audit)

| Pin | Where | What it covers (this audit does NOT re-pin it) |
| --- | --- | --- |
| Confirmation-gate semantics | `tests/test_trading_offline.py:184-216` (branch farm/T-0041) | "one cent above threshold → held until confirm=True"; exactly-at-threshold posts |
| Invalid params fail closed before fetch | `tests/test_trading_offline.py:247-296` | side HOLD, price 1.5, size 0, order_type IOC/GTD — rejected with zero get_market/post_order calls |
| Exposure cap with existing (matching-format) positions | `tests/test_trading_offline.py:160-183` | positions feed the cap; over-cap BUY rejected before posting — the MATCHING format case (complements SEC-ADVR-A2's divergence case) |
| Order kwargs pass-through | `tests/test_trading_offline.py:266-296` | post_order receives exactly token_id/price/size/side/order_type/expiration |
| Regular validation matrix | `tests/test_safety_limits.py` (branch farm/T-0032) | oversized order :93, exposure cap :116, sell-reduces :143, short-increases :169, liquidity :194, spread :214/:234, earliest-failure-wins :252, per-market matching :288, skip-without-market-id :311, cross-market SELL :327/:351, summary/properties :428-499, from-config mapping :501 |
| Gate reporting across tools | `tests/test_confirmation_gate.py` | blocked/allowed/propagation/batch-and-rebalance reporting |
| DEMO_MODE substitution + secret masking | `tests/test_config_security.py:101-186` (branch farm/T-0042) | substitution unconditional in demo mode; `to_dict` masks the four secrets |
| `has_api_credentials` semantics | `tests/test_config_security.py:212-233` | config requires KEY+PASSPHRASE+KEY_NAME (SECRET not checked) — cross-referenced by SEC-ADVR-C1's link A |
| MAX_SPREAD_TOLERANCE bounds | `tests/test_config_security.py:201-210` | 0.0/1.0 inclusive; outside rejected — the ONLY constrained limit field (contrast SEC-ADVR-D1) |
| Hermeticity precedent | `.agentfarm/verdicts/T-0032-sec.md` (P-0029) | env -i green-suite methodology this audit re-applies |

---

## 6. Out of Scope & Follow-ups

- **Key material in logs (P3 follow-ups, not audited in depth — the auth/signer
  slice is a future task):** `grep -rn "logger\." src/polymarket_mcp/tools/trading.py
  src/polymarket_mcp/auth/ | grep -i "key\|secret\|passphrase\|token"` →
  `auth/client.py:161` logs `api_key[:8]...` at INFO (partial L2 key in logs);
  `auth/client.py:228/:251` log `token_id` inside error messages (order token id,
  public data — benign); `server.py:391-392` log `POLYMARKET_API_KEY=...[:8]` /
  `POLYMARKET_PASSPHRASE=...[:8]` at DEBUG. Recommendation: drop the key/passphrase
  fragments from all log levels.
- **Prompt injection through market data:** SECURITY.md:43-44 declares it in
  scope, but the mitigation boundary is the model layer (the MCP server surfaces
  market text; enforcement is the LLM's policy). Out of scope for an offline code
  audit; noted for the response to issue #41.
- **Dashboard RCE/SSRF:** explicitly out of scope per SECURITY.md:45/:53.
- **Follow-up tasks fed by this audit (curated, in priority order):**
  1. SEC-ADVR-A1 (P1): NaN guard at order entry + NaN-safe limit comparisons.
  2. SEC-ADVR-B1/B2 (P1): in-flight exposure accounting (reserve-commit or
     per-plan validation) + optional serialization lock.
  3. SEC-ADVR-C1 (P1): enforce DEMO_MODE in tool initialization/entry; reword
     config.py:25-28.
  4. SEC-ADVR-D1 (P2): numeric constraints on the five limit fields.
  5. SEC-ADVR-A2 (P2): normalize/match market ids across both formats.
  6. Recording-fixture task (P3): capture real Data-API position payloads to
     settle A2's upstream-format reachability (offline fixtures, never live CI).
  7. Transport check (P3): verify the MCP JSON-RPC parser rejects NaN literals,
     or add explicit transport validation.
- **The response to issue #41** (whether/how to engage the external researcher) is
  a human/social decision and is routed to `REQUER-HUMANO`; reproductions here are
  unit-level and offline.

---

## 7. Responsible Disclosure

This audit was produced in the spirit of SECURITY.md:16-31. No exploit is being
published: all reproductions are unit-level, offline, and contained in this
repository's test suite (`tests/test_safety_adversarial.py`), which fails safe
(xfail-strict) until the underlying issues are fixed. Anyone reproducing a real
vulnerability against production should use the private channel at
SECURITY.md:20-24 (GitHub private vulnerability reporting) and allow the
maintainer the 7-day initial-response window before any public disclosure.
