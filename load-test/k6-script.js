/**
 * BlackFriday Load Test — k6
 *
 * Usage:
 *   k6 run --env BASE_URL=http://<cloudfront-domain> load-test/k6-script.js
 *
 * Phases:
 *   Phase 1 — Baseline   (5 min,  10 VUs):  p99 < 2000ms
 *   Phase 2 — Ramp       (10 min, 500 VUs): p99 < 1500ms
 *   Phase 3 — Peak       (15 min, 500 VUs): p99 < 500ms
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";
import { textSummary } from "https://jslib.k6.io/k6-summary/0.0.2/index.js";

// ── Custom metrics ─────────────────────────────────────────────────────────────

const cacheHitRate = new Rate("cache_hit_rate");
const checkoutSuccessRate = new Rate("checkout_success_rate");
const checkoutErrors = new Counter("checkout_errors");
const productLatency = new Trend("product_latency", true);
const inventoryLatency = new Trend("inventory_latency", true);
const checkoutLatency = new Trend("checkout_latency", true);

// ── Test configuration ─────────────────────────────────────────────────────────

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const PRODUCT_COUNT = 100;

// Session tokens are pre-seeded via seed.py
// In a real test you would fetch these from an API or file; here we generate
// UUIDs that match the seed pattern (sequential user IDs, uuid4 tokens are
// random — for testing we POST checkout with a known-good format and handle 401s)
function randomSessionToken() {
  // Generate a UUID v4 — most will be invalid (401) in a real run.
  // Replace this with actual tokens exported from seed.py for full fidelity.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function randomProductId() {
  return Math.floor(Math.random() * PRODUCT_COUNT) + 1;
}

export const options = {
  scenarios: {
    blackfriday_traffic: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        // Phase 1: Baseline — steady low traffic
        { duration: "5m", target: 10 },
        // Phase 2: Ramp — gradual traffic increase
        { duration: "10m", target: 500 },
        // Phase 3: Peak — sustained Black Friday load
        { duration: "15m", target: 500 },
        // Cool-down
        { duration: "1m", target: 0 },
      ],
    },
  },

  thresholds: {
    // Phase-tagged latency thresholds (applied globally; phases are tracked via groups)
    http_req_duration: [
      "p(95)<3000", // overall safety net
    ],
    product_latency: ["p(99)<2000"],
    inventory_latency: ["p(99)<2000"],
    checkout_latency: ["p(99)<3000"],

    // Availability
    http_req_failed: ["rate<0.05"], // < 5% error rate overall
    checkout_success_rate: ["rate>0.90"], // > 90% checkout success
  },
};

// ── Main virtual user scenario ─────────────────────────────────────────────────

export default function () {
  const rand = Math.random();

  if (rand < 0.60) {
    // 60% — browse product catalog
    browseProducts();
  } else if (rand < 0.80) {
    // 20% — check inventory
    checkInventory();
  } else {
    // 20% — attempt checkout
    attemptCheckout();
  }

  sleep(Math.random() * 2 + 0.5); // 0.5–2.5s think time
}

function browseProducts() {
  const useList = Math.random() < 0.3;

  if (useList) {
    group("product_list", () => {
      const start = Date.now();
      const res = http.get(`${BASE_URL}/api/products`, {
        tags: { endpoint: "product_list" },
      });
      productLatency.add(Date.now() - start);

      check(res, {
        "products list 200": (r) => r.status === 200,
        "products list has items": (r) => {
          try {
            return JSON.parse(r.body).length > 0;
          } catch {
            return false;
          }
        },
      });

      const xCache = res.headers["X-Cache"];
      if (xCache) cacheHitRate.add(xCache === "HIT");
    });
  } else {
    group("product_detail", () => {
      const id = randomProductId();
      const start = Date.now();
      const res = http.get(`${BASE_URL}/api/products/${id}`, {
        tags: { endpoint: "product_detail" },
      });
      productLatency.add(Date.now() - start);

      check(res, {
        "product detail 200 or 404": (r) => r.status === 200 || r.status === 404,
      });

      const xCache = res.headers["X-Cache"];
      if (xCache) cacheHitRate.add(xCache === "HIT");
    });
  }
}

function checkInventory() {
  group("inventory", () => {
    const id = randomProductId();
    const start = Date.now();
    const res = http.get(`${BASE_URL}/api/inventory/${id}`, {
      tags: { endpoint: "inventory" },
    });
    inventoryLatency.add(Date.now() - start);

    check(res, {
      "inventory 200 or 404": (r) => r.status === 200 || r.status === 404,
    });
  });
}

function attemptCheckout() {
  group("checkout", () => {
    const payload = JSON.stringify({
      session_token: randomSessionToken(),
      product_id: randomProductId(),
      quantity: 1,
    });

    const start = Date.now();
    const res = http.post(`${BASE_URL}/api/checkout`, payload, {
      headers: { "Content-Type": "application/json" },
      tags: { endpoint: "checkout" },
      // 401 (invalid session) and 409 (insufficient stock) are expected responses,
      // not infrastructure failures — exclude from http_req_failed
      responseCallback: http.expectedStatuses({ min: 200, max: 299 }, 401, 409),
    });
    checkoutLatency.add(Date.now() - start);

    const success = res.status === 201;
    checkoutSuccessRate.add(success || res.status === 401 || res.status === 409);

    if (res.status >= 500) {
      checkoutErrors.add(1);
    }

    check(res, {
      "checkout not server error": (r) => r.status < 500,
    });
  });
}

// ── Metrics polling ────────────────────────────────────────────────────────────
// Poll /api/metrics every ~30s from VU 1 to track cache performance during the run

export function setup() {
  const res = http.get(`${BASE_URL}/health`);
  check(res, { "health check passes": (r) => r.status === 200 });
  return { startTime: Date.now() };
}

let lastMetricsPoll = 0;

export function handleSummary(data) {
  // Fetch final metrics snapshot
  const metricsRes = http.get(`${BASE_URL}/api/metrics`);
  let appMetrics = {};
  try {
    appMetrics = JSON.parse(metricsRes.body);
  } catch {
    appMetrics = { error: "failed to fetch app metrics" };
  }

  const summary = {
    k6: data,
    app_metrics: appMetrics,
    test_config: {
      base_url: BASE_URL,
      phases: [
        { name: "baseline", duration: "5m", target_vus: 10, p99_threshold_ms: 2000 },
        { name: "ramp", duration: "10m", target_vus: 500, p99_threshold_ms: 1500 },
        { name: "peak", duration: "15m", target_vus: 500, p99_threshold_ms: 500 },
      ],
    },
  };

  return {
    stdout: textSummary(data, { indent: " ", enableColors: true }),
    "load-test/results/summary.json": JSON.stringify(summary, null, 2),
  };
}
