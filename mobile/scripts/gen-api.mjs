#!/usr/bin/env node
/**
 * npm run gen:api — regenerate the mobile API client from the backend's OpenAPI schema.
 *
 * Types flow one way: the backend publishes OpenAPI, mobile generates from it. Nothing in
 * src/api is hand-maintained (CLAUDE.md §2).
 *
 * Today this fetches and snapshots the schema. Generating the typed client and TanStack Query
 * hooks needs a generator dependency (openapi-typescript or similar), which needs approval
 * before it is added (CLAUDE.md §7) — so this script stops at the schema and says so rather
 * than pretending to have produced a client.
 */

import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, '../src/api/openapi.json');
const BASE = process.env.ANUPALAN_API_URL ?? 'http://localhost:8000';
const URL_ = `${BASE}/openapi.json`;

try {
  const response = await fetch(URL_);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const schema = await response.json();
  await mkdir(dirname(OUT), { recursive: true });
  await writeFile(OUT, `${JSON.stringify(schema, null, 2)}\n`, 'utf8');

  const paths = Object.keys(schema.paths ?? {}).length;
  console.log(`schema: ${URL_} -> src/api/openapi.json (${paths} paths)`);
  console.log('client generation is not wired yet — see scripts/gen-api.mjs (P3, FR-20).');
} catch (error) {
  console.error(`could not fetch ${URL_}: ${error.message}`);
  console.error('is the backend running?  make api   (or: cd backend && uvicorn app.main:app)');
  console.error('override the host with ANUPALAN_API_URL.');
  process.exitCode = 1;
}
