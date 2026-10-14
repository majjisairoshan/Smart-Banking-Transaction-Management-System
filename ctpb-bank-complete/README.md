# CTPB Bank — Banking Transaction System

> **Computational Thinking & Programming — course project.**
> A full-stack banking web application (PostgreSQL database **`CTPBD`**) with customer and
> administrator portals: secure login, account validation, balance enquiry, atomic money
> transfer, savings & current account management, fraud flags, and a concurrent,
> idempotent interest-accrual engine.

---

## 1. Problem → Computational Thinking → Solution

```
Real-World Problem:  A bank needs a safe web channel where customers check balances,
                     validate payees and move money — while staff watch the books.
        │
        ▼ Decompose
  ① Authenticate (two roles)   ② Represent money & accounts (invariants!)
  ③ Validate a payee account   ④ Move money atomically (never half-done)
  ⑤ Record an auditable ledger ⑥ Detect risky behaviour  ⑦ Administer the book
        ▼ Abstract
  Account = abstract base with polymorphic rules; Transaction = double-entry ledger row;
  Transfer = pure plan + single DB transaction; Report = fold over the ledger.
        ▼ Algorithms & Data Structures
  merge sort (page re-ordering) · binary search · sliding-window velocity counter ·
  greedy note breakdown · top-K · deque rate limiter · indexed SQL access paths
        ▼ Implement (this repo)  →  Test (unit + property + integration)  →  Defend
```

### Feature ↔ problem-statement mapping

| Requirement | Where |
|---|---|
| **Validate Account** | Dashboard → “✓ Validate account”, pre-transfer validation step, `POST /api/validate-account`, `BankingService.validate_account` |
| **Check Balance** | Live balance cards (auto-refresh 25 s), sparkline of running total, `GET /api/balance` |
| **Transfer Money** | Two-step transfer wizard, `POST /api/transfer`, `BankingService.transfer` — atomic + idempotent |
| **Update both Savings & Current accounts** | Polymorphic `SavingsAccount`/`CurrentAccount` (`bank/models.py`), both updated in one DB transaction; profile lists both; admin can open/freeze either |
| **Login for user & admin** | `/login` (gold theme) and `/admin/login` (teal theme) with separate role guards + rate limiting |

---

## 2. Architecture

```
templates/  ──►  bank/routes/  ──►  bank/services.py  ──►  bank/repository.py  ──►  PostgreSQL: CTPBD
 (Jinja2)      auth|user|admin|api   (use-cases, pure        (all SQL lives here)      users
static/        (Flask blueprints)     rules in plan_transfer)                          accounts
 css/js                                                                              transactions
                                  bank/models.py  — domain: Account ABC → Savings | Current
                                  bank/algorithms.py — merge sort, binary search, greedy, risk
                                  bank/db.py — thread-safe pooled connections (Singleton)
```

* **Design patterns:** Singleton (connection pool), Repository (all SQL isolated),
  Factory (`account_from_row` rebuilds the right subtype), Template Method
  (`Account` base class with overridden floors), Decorator (`login_required`).
* **Layering rule:** routes never contain SQL; repositories never contain business rules;
  `plan_transfer` is pure and I/O-free → property-testable.

### Data model (CTPBD)

```
users ─────────────────┐
 id  username  role    │ 1        n accounts ─────────────────────────┐
 ── admin / user ◄─────┘             id | account_number | type | balance | status   │
                                      │ savings: min ₹1,000 · 4% p.a.                │ 1
                                      │ current: ₹50,000 overdraft · 0%              │
                                      └──────────────┬───────────────────────────────┘
                                                     │ n (either side)
                                            transactions (double-entry ledger)
                              txn_ref | idempotency_key | from | to | amount |
                              type | status | note | sender_after | receiver_after
```

Hard guarantees in the schema: `CHECK` constraints on enums & positivity, `UNIQUE(user_id, account_type)`
(one savings + one current per customer), `UNIQUE idempotency_key`, partial index on flagged rows.

---

## 3. Course-rubric coverage

| Rubric | Evidence |
|---|---|
| **1. Problem solving & computational thinking** | Decomposition above; `bank/algorithms.py`; complexity table §4 |
| **2. Programming & data structures** | Type-hinted Python; Decimal money; enums; generators (`reduce`/comprehensions for totals & charts); context managers everywhere (`with pool.connection()`); performance notes §7 |
| **3. Software design & engineering** | OOP: abstract `Account` → subtypes; repository pattern; DTOs; services; blueprints; `StrEnum`; generics (`TypeVar`, `Callable[[Any], T]` row mappers) |
| **4. Functional programming & concurrency** | Pure `plan_transfer`, `assess_transfer_risk`, `greedy_denominations`; higher-order `merge_sort(key=…)`; `reduce` folds; `ThreadPoolExecutor` interest engine; deadlock-free row locking; GIL discussion §5 |
| **5. Software quality** | 70+ tests: unit, **property-based (Hypothesis)**, live-PG integration, Flask end-to-end; **85% coverage**; ruff (lint) clean; mypy clean; CI workflow |
| **6. AI-assisted engineering** | §9 — specification-first prompts, review loop, bugs found during validation |

---

## 4. Algorithms & complexity

| Algorithm | Where | Why this one | Time | Space |
|---|---|---|---|---|
| **Merge sort** (divide & conquer, stable) | transaction page re-sorting, `top_k` | Θ(n log n) guaranteed + stable (FIFO on equal timestamps) — safe on adversarial input | Θ(n log n) | Θ(n) |
| **Binary search** | `algorithms.binary_search` (ledger lookups on sorted runs) | O(log n) beats O(n) scan on sorted data | O(log n) | O(1) |
| **Greedy denominations** | “🏧 Note breakdown” widget | INR is a canonical coin system → greedy is provably optimal (DP would be needed for arbitrary systems) | O(k), k=10 notes | O(k) |
| **Sliding window** | transfer velocity check (fraud rule) | newest-first timestamps + early exit → O(k), not O(n) | O(k) | O(1) |
| **Top-K** | “largest transactions” (admin) | merge-sorted prefix; heapq.nlargest documented as O(n log k) alternative | O(n log n) | O(n) |
| **Deque rate limiter** | login throttling | amortised O(1) push/pop for sliding-window counters | O(1) amortised | O(window) |
| **DB indexes** | `schema.sql` (B-trees on account_number, FK + created_at, partial on flagged) | point lookups O(log n); recent-history scans use the index, never seq-scan the ledger | — | — |
| **Connection pool** | `bank/db.py` | O(1)-amortised connection reuse vs ~10–50 ms fresh TCP+auth per query | — | bounded |

**Amortized vs expected (viva talking points):** pool checkout is O(1) amortised (bounded queue under
contention); account-number allocation is *expected* O(1) with birthday-bound retries;
page renders are O(m log m) for the merge-sort of `m` page rows — measured live and shown
in the UI (`⚡ merge sort · N µs`).

---

## 5. Concurrency & the GIL

| Mechanism | Used for | Why correct here |
|---|---|---|
| **Threaded Flask + ThreadedConnectionPool** | serving many users at once | DB work is **I/O-bound**; psycopg2 releases the GIL on socket waits → threads overlap fine |
| **`SELECT … FOR UPDATE ORDER BY id`** | transfer row locking | deterministic lock order ⇒ **deadlock-free**; ledger + balances commit in *one* transaction |
| **Idempotency keys (`UNIQUE`)** | double-clicks, retries, network replays | at-least-once delivery with **exactly-once effect** — reruns return the original transaction |
| **ThreadPoolExecutor (workers ≤ pool size)** | monthly interest accrual | per-account transactions in parallel; a failure on one account never poisons the batch |
| **Atomic `UPDATE … balance = balance + %s`** | balance mutation | single SQL statement — no read-modify-write race between Python statements |
| **Deques + `threading.Lock`** | login rate limiting under threads | lock-free reads elsewhere; one tiny critical section |

**Why not multiprocessing / asyncio?** The workload is dominated by PostgreSQL round-trips
(I/O-bound), cheap per request; threads give real parallelism for that without the IPC cost of
processes. Async would help at 10⁴+ concurrent sockets — documented as a scale-out step, but
out of scope for a course deployment. **CPU-bound** work (e.g. bulk statement PDF generation)
*would* justify multiprocessing — this trade-off is defensible in the viva.

---

## 6. Connect it to your PostgreSQL (`CTPBD`)

The app reads environment variables (see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `DB_NAME` | **`CTPBD`** | database name |
| `DB_HOST` / `DB_PORT` | `localhost` / `5432` | server |
| `DB_USER` / `DB_PASSWORD` | `postgres` / `postgres` | credentials |
| `DATABASE_URL` | — | full DSN; **overrides the parts above** (containers/CI) |
| `FLASK_SECRET_KEY` | dev value | set a long random secret in production |

### Quick start (your machine)

```bash
# 1) create the database (or let the script do it):
python -m scripts.seed --create-db --seed      # creates CTPBD, schema, demo data

# 2) install + run
pip install -r requirements.txt
python app.py                                  # http://localhost:5000
```

```bash
# Docker (nothing else to install):
docker compose up --build                      # app :5000, postgres with CTPBD volume
```

### Demo credentials (seeded)

| Portal | Username | Password |
|---|---|---|
| Customer | `aarav.sharma` | `User@123` |
| Customers (others) | `priya.nair` · `rohan.verma` · `meera.iyer` · `karan.malhotra` | `User@123` |
| **Admin** | `admin` | `Admin@123` |

### Suggested live-demo flow (≈5 min)

1. `/login` as `aarav.sharma` → dashboard: animated balances, sparkline, flow donut, monthly bars.
2. “✓ Validate account” → paste Priya’s account number (find it via admin if needed) → name chip appears.
3. “⇄ New transfer” → validate → ₹750 → live note breakdown → **Send** → toast with `TXN…` ref; balances update.
4. Send the same form twice (or click fast) → **same ref back** (idempotency proof).
5. Fire 4 quick transfers → 4th gets **⚑ flagged** (velocity rule); show it in admin “Flagged queue”.
6. Transactions page → change “Sort” → note the honest `⚡ merge sort · N µs` chip.
7. `/admin/login` as `admin` → “▶ Run interest accrual” **twice** → second flash shows 0 new credits
   (idempotent batch). Freeze + unfreeze an account in Customers.

---

## 7. Testing & quality engineering

```bash
pytest -q                 # unit + property (fast, no DB needed)
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ctpbd_test pytest -q   # + integration & web
ruff check .              # lint — clean
mypy                      # static types — clean
coverage run -m pytest && coverage report
```

Measured on this machine: **72 tests passing** — 64 unit/property + 8 live-DB integration & end-to-end web tests; **85% line coverage**
(algorithms 100%, models 99%, security 94%, utils 95%, services 83%).

**Property-based testing (Hypothesis)** generates hundreds of hostile inputs to prove:
- **conservation of money**: total balance before == after for every transferrable amount;
- merge sort ≡ `sorted()` on random lists (both directions);
- greedy denominations always reconstruct the amount exactly;
- `inr()` ↔ `parse_amount()` round-trip over random Decimals.

**CI/CD:** `.github/workflows/ci.yml` runs ruff → mypy → pytest (with a PostgreSQL 16
service container) → coverage gate (`--fail-under=70`) on every push.
**Containerisation:** `Dockerfile` + `docker-compose.yml` (health-gated startup; seed on first boot).

**Performance notes:** pooled connections; indexed access paths verified with
`EXPLAIN` on the hot queries; page sorts bounded to page size `m`; interest batch parallel ×4;
balance refresh is one indexed query per 25 s; connection pool capped at 10 to protect Postgres.

---

## 8. API reference (JSON)

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /api/validate-account` | any session | `{account_number}` → found/usable/holder/type/status |
| `GET /api/balance` | customer | live balances + total |
| `POST /api/transfer` | customer | `{from_account_id, to_account_number, amount, note, idempotency_key}` → ref/status/flags |
| `GET /api/denominations?amount=N` | any session | greedy INR note breakdown |
| `GET /api/health` | public | container health probe (`db: up/down`) |

---

## 9. AI-assisted development & code review (responsible-use log)

Built with an AI pair-programmer under a **specification-first** workflow:

1. **Spec-first prompting** — the problem statement was decomposed into numbered,
   testable requirements (invariants ledger, idempotency, role separation) *before*
   any code request, so generated code had explicit acceptance criteria.
2. **Context management** — generated module-by-module (models → repositories →
   services → routes → UI) with interfaces kept stable between prompts, avoiding
   the “whole-app-in-one-prompt” drift.
3. **Critical review of AI output — bugs actually caught in validation:**
   - *Abstract-class instantiation*: the repository’s `create()` initially built the
     abstract `Account` directly — a `TypeError` surfaced by the seed run; fixed by routing
     through the factory (which is now explicitly unit-tested).
   - *Invariant-breaking seed*: the first seed wrote a −₹1,47,400 balance, tripping the DB
     `CHECK` constraint; replaced with a simulate-then-persist ledger that skips any event
     violating account floors — a case of tests/data pushing back on generated code.
   - *Jinja/dict collision*: `d.items` silently bound to `dict.items()` (500 page);
     renamed the key and added web smoke tests so the class of bug can’t regress.
   - *Failing test I wrote*: an overdraft boundary test used the exact boundary value
     (₹51,000 → floor is inclusive) — the failing test, not the code, was wrong; fixed the test.
4. **Verification, not trust** — every AI-produced path was executed: ruff, mypy,
   70+ tests (incl. adversarial Hypothesis properties), curl-based API replay and a
   scripted end-to-end demo. Screenshots/outputs are evidence, generated code is not
   trusted uncritically.
5. **Human ownership** — schema invariants, deadlock ordering, idempotency design and
   the demo narrative were human-specified; the AI accelerated typing and broadened
   test coverage; final reading of every file was manual.

---

## 10. Security checklist & honest limitations

**In place:** scrypt password hashing · role-guarded sessions (HttpOnly, SameSite=Lax, 30‑min) ·
sliding-window login rate limit (5/5 min) · full audit ledger with before/after balances ·
parameterised SQL everywhere (no string-built queries) · input normalisation & strict amount
regex · frozen-account enforcement on both sides of a transfer · server-side ownership checks.

**Documented scope for a course demo:** no CSRF tokens on form posts (SameSite=Lax + idempotency
mitigate the realistic risk; add `Flask-WTF` next), no MFA, no TLS in the dev server
(terminate TLS at a proxy for deployment), fraud engine is rule-based (would evolve to a
scoring model), scaling story is single-node (pool + indexes first, then read replicas).

---

## 11. Repository map

```
app.py                   entry point + app factory
bank/
  config.py              env-driven settings (DATABASE_URL → CTPBD)
  db.py                  thread-safe connection pool (Singleton) + schema bootstrap
  models.py              Account ABC, Savings/Current subtypes, Transaction, DTOs
  repository.py          all SQL (Repository pattern)
  services.py            use-cases: validate/balance/transfer/history/interest + pure plan_transfer
  algorithms.py          merge sort, binary search, greedy, sliding-window risk engine
  security.py            password hashing, login_required decorator, rate limiter
  utils.py               INR formatting, masking, parsing, id generation
  routes/                auth · user · admin · api (Flask blueprints)
db/schema.sql            tables, constraints, indexes (idempotent)
scripts/seed.py          DB creation + consistent-ledger demo data
templates/ static/       UI (dark fintech theme, generated imagery)
tests/                   unit · property-based · live-PG integration · web smoke
Dockerfile, docker-compose.yml, .github/workflows/ci.yml, pyproject.toml
```
