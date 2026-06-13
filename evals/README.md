# Observatory — Eval Harness

Three-layer test coverage for the Observatory. Layer 1 gates Layer 2 — run them in order or use `npm test` to chain both automatically.

## Layer overview

| Layer | File | Run command | What it checks |
|---|---|---|---|
| 1 | `evals/smoke.ts` | `npm run test:smoke` | HTTP status + response shape for all API routes |
| 2 | `evals/browser/smoke.spec.ts` | `npm run test:browser` | UI interactions, layout, search, detail overlay, brain map |
| 3 | `evals/product-evals.md` | Manual — read and check | Golden behaviors for vibe-coded changes |

## Prerequisites

**Before running any tests:**
```bash
./run.sh --serve &    # start Observatory server on port 8000
```

**Before Layer 2 browser tests hit `/` (dashboard):**
```bash
./run.sh              # build dashboard.html (gitignored — must be built locally)
```
Layer 2 tests that visit `GET /` will return 404 if `dashboard.html` hasn't been built. This is expected on a fresh clone. Run `./run.sh` (without `--serve`) first to generate it.

**If port 8000 is occupied by another server:**
```bash
OBS_PORT=8001 npm run test:smoke
OBS_PORT=8001 npm run test:browser
```

## Run commands

```bash
# All layers (Layer 1 gates Layer 2)
npm test

# Layer 1 only — fast HTTP sanity check (~5s)
npm run test:smoke

# Layer 2 only — browser automation (~60s)
npm run test:browser

# Layer 2 interactive mode
npx playwright test --ui

# Layer 3 — open product-evals.md and follow manually
```

## When to run which layer

| Changed | Run |
|---|---|
| `server.py` API routes | Layer 1 + Layer 2 |
| `dashboard.html` template / `build_dashboard.py` | Layer 2 + Layer 3 (Dashboard section) |
| `brain.html` / `build_brain.py` | Layer 2 brain tests + Layer 3 Brain section |
| Search / detail overlay JS | Layer 2 search+detail tests + Layer 3 Search section |
| Watchlist JS or DB schema | Layer 1 watchlist check + Layer 3 Watchlist section |
| Rec cards / `build_profile.py` | Layer 2 rec count tests + Layer 3 Rec cards section |
| Any CSS or layout change | Layer 2 layout tests + Layer 3 Mobile section |

## When to add an eval

**Two triggers — not one:**

1. **New feature ships** → write one eval for the new externally observable behavior. Feature = route, endpoint, UI state, scheduled job, webhook, or data mutation. Refactors and copy changes don't count.

2. **Bug fixed** → write the check that would have caught this failure. Add to `evals/smoke.ts` (HTTP), a Playwright spec (UI), or a product-evals section (manual behavior).

**When to remove an eval:** when the feature it covers is removed. A test for a deleted route or removed UI element is noise that hides real failures.

## Adding a Layer 1 check (smoke.ts)

Add an entry to the `checks` array in `evals/smoke.ts`:
```ts
{
  label: "GET /api/my-route — returns expected shape",
  url: "/api/my-route",
  expectedStatus: 200,
  validate: (_, body) =>
    Array.isArray(body) ? null : `expected array, got ${typeof body}`,
},
```

## Adding a Layer 2 test (Playwright)

1. Add `.spec.ts` in `evals/browser/`
2. Tag read-only tests: `// @readonly` in file header
3. Tag mutating tests: `// @mutating` — add `test.skip(!!process.env.CI)` at the top
4. Use `data-testid` selectors where possible — add them to components at the same time
5. Tests must be independent — no shared state between tests

## Candidate evals

<!-- Claude writes here during ticket completion (Step 6) when a check isn't written yet.
     Each entry: what to test, which layer, why it matters. -->
