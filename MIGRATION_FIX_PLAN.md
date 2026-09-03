# Migration & DB Design — Fix Plan

Ordered by priority from the audit. The `portfolios` decision in Step 0 branches the P0 fix — do that check first, then apply only the matching migration below (they're mutually exclusive).

---

## Step 0 — Confirm: is `portfolios` actually dead?

- Rails: `grep -rn "Portfolio" app/models app/controllers` in `intelligence-platform-api`
- Python: same grep for a SQLAlchemy model in `intelligence-platform-stock`
- Prod DB: `SELECT count(*) FROM portfolios;` and the three `portfolio_*` tables

If all zero and nothing references them in code, it's dead — use **Option A**. If something still touches it, use **Option B**.

---

## P0 — Fix 5.1 (+ 5.6): the circular FK

### Option A — Retire `portfolios` (recommended if Step 0 confirms it's dead)

### Option A — Retire `portfolios` (recommended if Step 0 confirms it's dead)

Drops all six portfolio tables (`portfolios`, `portfolio_holdings`,
`portfolio_recommendations`, `portfolio_allocation_history`,
`portfolio_rebalance_trades`, `portfolio_drift_alerts`) in one Alembic
migration. Dropping `portfolios` also removes the FK Rails' R2 added to
it, so no separate Rails migration is needed for teardown.

→ see `0017_retire_portfolio_tables.py`

After this lands: delete R2's *file* (`db/migrate/20260810024236_add_user_id_to_portfolios.rb`) from the Rails repo. This is safe even though R2 already ran everywhere — Rails only checks the `schema_migrations` table for the timestamp string, not that the file still exists, so removing it doesn't roll anything back. (It does mean `rails db:rollback` can no longer target that specific migration by name — acceptable for a table you're deleting anyway.) Regenerate `schema.rb` afterward.

### Option B — Keep `portfolios` (if it's actually still in use somewhere)

Move DDL ownership of the FK to Alembic, guarded the same way P16 guards on `users`/`companies`.

→ see `0017_add_user_id_to_portfolios.py`

Then delete `db/migrate/20260810024236_add_user_id_to_portfolios.rb` from Rails — same reasoning as above.

---

## P0 — Fix 5.2: fresh-DB bootstrapping ambiguity

Root cause: `rails db:prepare` schema-loads `schema.rb` (which contains every Alembic table) whenever `schema_migrations` is empty — then `alembic upgrade head` collides with tables that already exist.

**Fix: stop using `db:prepare` in the automated path.** Switch to `db:migrate`, which only replays the (now 2, after Option A) Rails migrations and never touches `schema.rb`.

`docker-compose.yml`:
```diff
   rails-migrate:
     build: ./intelligence-platform-api
-    command: bundle exec rails db:prepare
+    command: bundle exec rails db:migrate
     depends_on:
       postgres:
         condition: service_healthy
```

Also verify `python-migrate` actually *waits for rails-migrate to exit*, not just start — `depends_on` without a completion condition is the single most common cause of exactly this race:
```diff
   python-migrate:
     build: ./intelligence-platform-stock
     command: alembic upgrade head
     depends_on:
       rails-migrate:
-        condition: service_started
+        condition: service_completed_successfully
```
If it's already `service_completed_successfully`, no change needed — but check the literal file, don't assume.

Keep `schema.rb` for local `rails db:schema:load` convenience, but stop treating it as part of the automated provisioning path — with two independent DDL owners on one DB, only migration-replay is safe end-to-end.

---

## P1 — the stamp-heuristic entrypoint (not covered by this audit)

Separately from this report: we'd previously traced a live incident to a custom Alembic entrypoint that stamps `alembic_version` straight to `head` whenever `companies` exists, without checking that every Python-only migration actually ran — that's what caused `relation "embeddings" does not exist` in prod.

**Find this script first and confirm which branch it takes today** — it's the one item here that's already caused an outage, and it isn't mentioned anywhere in the audit, so either it's since been replaced by the plain `alembic upgrade head` the report describes (good) or it's still live (bad, fix immediately). If it's still there, replace table-existence checks with an actual revision comparison:

```python
# BEFORE (buggy): assumes Rails-created tables imply full Python history
if table_exists("companies"):
    stamp("head")
else:
    upgrade("head")

# AFTER: compare applied revision against the real head
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

script = ScriptDirectory.from_config(alembic_cfg)
with engine.connect() as conn:
    current = MigrationContext.configure(conn).get_current_revision()

if current == script.get_current_head():
    pass  # already fully migrated
elif current is None and table_exists("companies"):
    # DB was schema-loaded, not migrated — stamp to a KNOWN-SAFE
    # baseline, never straight to head, then run the remainder
    stamp(KNOWN_SCHEMA_LOAD_BASELINE_REVISION)
    upgrade("head")
else:
    upgrade("head")
```

---

## P1 — Fix 5.3: embedding dimension default

`app/core/config.py`:
```diff
- EMBEDDING_DIMENSIONS: int = 1536
+ EMBEDDING_DIMENSIONS: int = 3072
```

Add a startup assertion so a future dimension change fails loudly instead of silently:
```python
actual_width = conn.execute(text(
    "SELECT atttypmod FROM pg_attribute "
    "WHERE attrelid = 'embeddings'::regclass AND attname = 'embedding'"
)).scalar()
expected = settings.EMBEDDING_DIMENSIONS
if actual_width is not None and actual_width != expected:
    raise RuntimeError(
        f"EMBEDDING_DIMENSIONS={expected} but DB column is vector({actual_width})"
    )
```

---

## P2 — Fix 5.5: redundant index on `company_news`

Low-risk cosmetic cleanup — drop the plain index P1 created, now redundant with P5's unique constraint:
```python
def upgrade():
    op.drop_index("ix_company_news_company_news", table_name="company_news")

def downgrade():
    op.create_index("ix_company_news_company_news", "company_news", ["company_id", "news_id"])
```

**Skip 5.7 as written** — `stock_prices`' unique constraint from P3 already backs an equivalent compound index on `(company_id, interval, timestamp)`; there's no query-plan gap, just a naming mismatch with the ORM's separately declared `Index(...)`. Not worth a migration.

---

## P3 — Fix 5.8: batch the P16 backfill (forward-looking only)

P16 already ran wherever it matters, so this isn't something to rewrite historically. For any environment that hasn't run it yet:
```python
BATCH_SIZE = 500
user_ids = [r[0] for r in conn.execute(text("SELECT id FROM users ORDER BY id"))]
for i in range(0, len(user_ids), BATCH_SIZE):
    chunk = user_ids[i:i + BATCH_SIZE]
    conn.execute(text("""
        INSERT INTO user_companies (user_id, company_id)
        SELECT u.id, c.id FROM users u CROSS JOIN companies c
        WHERE u.id = ANY(:chunk)
        ON CONFLICT DO NOTHING
    """), {"chunk": chunk})
    conn.commit()
```
If `users`/`companies` are expected to stay small, this is optional — just document that assumption in the migration docstring.