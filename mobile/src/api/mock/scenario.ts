/**
 * Scenario switch for the mock backend.
 *
 * The degradation paths in docs/01-architecture.md §11 are **acceptance criteria**, not edge
 * cases: no marker must offer a no-measurement mode, a low-confidence field must reach the
 * confirmation sheet, an unavailable LLM must still produce a report. None of that can be built
 * against a backend that only ever succeeds, so the mock can be told to fail in each of those
 * specific ways.
 *
 * Exposed in Settings under `__DEV__` only.
 */

export const SCENARIOS = [
  'happy',
  'no-marker',
  'low-confidence',
  'llm-unavailable',
  'offline',
  'server-error',
] as const;

export type Scenario = (typeof SCENARIOS)[number];

export const SCENARIO_LABELS: Record<Scenario, string> = {
  happy: 'Everything works',
  'no-marker': 'No marker detected',
  'low-confidence': 'Low-confidence field',
  'llm-unavailable': 'LLM unavailable',
  offline: 'Offline',
  'server-error': 'Server error',
};

let current: Scenario = 'happy';

const listeners = new Set<(scenario: Scenario) => void>();

export function getScenario(): Scenario {
  return current;
}

export function setScenario(scenario: Scenario): void {
  current = scenario;
  for (const listener of listeners) listener(scenario);
}

export function subscribeToScenario(listener: (scenario: Scenario) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
