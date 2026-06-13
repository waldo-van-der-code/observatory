/**
 * Layer 1 — HTTP smoke checks.
 * Run: npx tsx evals/smoke.ts
 * Requires: Observatory server running on http://localhost:$OBS_PORT (default 8000)
 *   ./run.sh --serve
 * Exit code 1 if any check fails.
 */

const PORT = process.env.OBS_PORT ?? "8000";
const BASE = `http://localhost:${PORT}`;

interface Check {
  label: string;
  url: string;
  expectedStatus: number | number[];
  validate?: (res: Response, body: unknown) => string | null;
}

async function run(checks: Check[]): Promise<void> {
  let failures = 0;

  for (const check of checks) {
    let res: Response;
    try {
      res = await fetch(`${BASE}${check.url}`);
    } catch {
      console.error(`❌ ${check.label} — connection refused (is Observatory running on port ${PORT}?)`);
      failures++;
      continue;
    }

    const expected = Array.isArray(check.expectedStatus)
      ? check.expectedStatus
      : [check.expectedStatus];

    if (!expected.includes(res.status)) {
      console.error(
        `❌ ${check.label} — expected ${expected.join(" or ")} got ${res.status}`
      );
      failures++;
      continue;
    }

    if (check.validate) {
      let body: unknown;
      try {
        const ct = res.headers.get("content-type") ?? "";
        body = ct.includes("json") ? await res.json() : await res.text();
      } catch {
        body = null;
      }
      const err = check.validate(res, body);
      if (err) {
        console.error(`❌ ${check.label} — ${err}`);
        failures++;
        continue;
      }
    }

    console.log(`✅ ${check.label} (${res.status})`);
  }

  if (failures > 0) {
    console.error(`\n${failures} check(s) failed.`);
    process.exit(1);
  } else {
    console.log(`\nAll ${checks.length} checks passed.`);
  }
}

const checks: Check[] = [
  // Identity check first — verifies the Observatory (not some other server) is answering.
  // Observatory's /api/brain/zones returns a JSON array of zone objects with {id, label} shape.
  // Other servers (e.g. steuermentoring) return 404 for this route.
  {
    label: "Server identity — /api/brain/zones returns 200 with JSON array of zone objects",
    url: "/api/brain/zones",
    expectedStatus: 200,
    validate: (_, body) => {
      if (!Array.isArray(body))
        return `expected JSON array, got ${typeof body} — wrong server may be running on this port`;
      if (body.length > 0 && !("id" in body[0] && "label" in body[0]))
        return `array items missing {id, label} — unexpected server response`;
      return null;
    },
  },
  {
    label: "GET / — dashboard HTML (200 or 404 if dashboard not built)",
    url: "/",
    expectedStatus: [200, 404],
    validate: (res) => {
      const ct = res.headers.get("content-type") ?? "";
      if (res.status === 200 && !ct.includes("text/html"))
        return `expected text/html, got ${ct}`;
      return null;
    },
  },
  {
    label: "GET /brain — brain.html (static, always present)",
    url: "/brain",
    expectedStatus: 200,
    validate: (res) => {
      const ct = res.headers.get("content-type") ?? "";
      return ct.includes("text/html") ? null : `expected text/html, got ${ct}`;
    },
  },
  {
    label: "GET /api/search?q=inception&type=film — returns JSON array",
    url: "/api/search?q=inception&type=film",
    expectedStatus: 200,
    validate: (_, body) =>
      Array.isArray(body) ? null : `expected array, got ${typeof body}`,
  },
  {
    label: "GET /api/search?q=dune&type=all — returns JSON array",
    url: "/api/search?q=dune&type=all",
    expectedStatus: 200,
    validate: (_, body) =>
      Array.isArray(body) ? null : `expected array, got ${typeof body}`,
  },
  {
    label: "GET /api/watchlist — returns JSON array (empty [] on fresh DB is fine)",
    url: "/api/watchlist",
    expectedStatus: 200,
    validate: (_, body) =>
      Array.isArray(body) ? null : `expected array, got ${typeof body}`,
  },
  {
    label: "GET /api/related/nonexistent — 200 or 404, not 500",
    url: "/api/related/nonexistent:id:0",
    expectedStatus: [200, 404],
  },
  {
    label: "GET /api/search (missing q) — 422 FastAPI validation error",
    url: "/api/search",
    expectedStatus: 422,
  },
];

await run(checks);
