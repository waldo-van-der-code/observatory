# Observatory — Eval Harness

## Candidate evals

<!-- Claude writes here during ticket completion (Step 6) when no harness layer exists yet.
     Each entry should include: what to test, which block/layer, why it matters. -->

## When to add an eval

**Two triggers — not one:**

1. **New feature ships** → write one eval for the new externally observable behavior. Feature = route, endpoint, UI state, scheduled job, webhook, data mutation, permission rule, email/notification flow, or third-party integration. Refactors, copy changes, and config updates don't count.

2. **Bug fixed** → write the check that would have caught this failure. Add to Block D in smoke.ts, or a new Playwright spec.

The harness grows from real outcomes — not speculation. After 30 tickets, 30+ tests. After 6 months, it's the project's institutional memory.

## Layer overview

| Layer 2 | evals/browser/*.spec.ts | Before push (local) | UI interactions, form fills, layout |

## Run commands

```bash
npx playwright test           # Layer 2 — all @readonly specs
npx playwright test --ui      # interactive mode when writing tests
```

## Adding a Layer 2 test (Playwright)

1. Add `.spec.ts` in `evals/browser/`
2. Tag read-only tests: `// @readonly` in file header
3. Tag mutating tests: `// @mutating` — these skip in CI (`test.skip(!!process.env.CI)`)
4. Use `data-testid` selectors — add them to components at the same time
5. Tests must be independent — no shared state between tests
