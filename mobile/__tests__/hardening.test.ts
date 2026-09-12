/**
 * Stage 13 — hardening (NFR-02, NFR-07, NFR-08).
 *
 * These are regression tests for four properties that are cheap to establish once and very easy to
 * lose silently afterwards:
 *
 * - **Hindi is complete.** It shipped incomplete for twelve stages on purpose, with an English
 *   fallback so a missing key never rendered as `settings.appearance`. The fallback stays, but the
 *   gap is now closed, and the only way it stays closed is a test that fails when a new English
 *   string lands without its Hindi.
 * - **Every text colour clears 4.5:1 on every ground it is drawn on.** The pass found three real
 *   failures. Contrast is invisible to review — nobody reads a hex value and sees 3.19:1 — so it is
 *   arithmetic, done here.
 * - **The cutover is still a folder deletion.** No app code may import the fixture layer except the
 *   two modules built to do it conditionally. That property is what makes Stage 13's "runs against
 *   the real backend with no screen changes" true, and one convenient import would end it.
 * - **The cold-start instrument does not lie.** It reports null rather than a made-up number when
 *   there is nothing to measure against, which is the difference between an honest NFR-02 figure and
 *   a zero someone pastes into a document.
 */

import { en } from '@/i18n/locales/en';
import { hi } from '@/i18n/locales/hi';
import { palettes } from '@/theme/tokens';
import {
  COLD_START_BUDGET_MS,
  bundleStartTime,
  markFirstFrame,
  resetStartupMeasurementForTests,
  startupMeasurement,
  withinBudget,
} from '@/lib/startup';

/**
 * Node's filesystem and path helpers, declared locally rather than project-wide.
 *
 * `tsconfig.json` deliberately leaves `node` out of `types` so the compiler catches an `fs` or a
 * `process` that wanders into `src/`. The cutover check below genuinely has to read the source tree,
 * so it declares the four functions it uses instead of weakening that guard for the whole app — the
 * same approach `reports.test.ts` takes for `Buffer`.
 */
declare function require<T>(id: string): T;
declare const __dirname: string;

const { readFileSync, readdirSync, statSync } = require<{
  readFileSync(path: string, encoding: 'utf8'): string;
  readdirSync(path: string): string[];
  statSync(path: string): { isDirectory(): boolean };
}>('node:fs');

const { join } = require<{ join(...parts: string[]): string }>('node:path');

type Node = Record<string, unknown>;

/** Every dot-path in a translation bundle that resolves to a string. */
function leafPaths(node: Node, prefix = ''): string[] {
  return Object.entries(node).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') return [path];
    if (value && typeof value === 'object') return leafPaths(value as Node, path);
    return [];
  });
}

// ---------------------------------------------------------------- NFR-08

describe('Hindi completeness', () => {
  const enPaths = leafPaths(en as unknown as Node);
  const hiPaths = leafPaths(hi as unknown as Node);

  it('has a Hindi string for every English string', () => {
    const missing = enPaths.filter((path) => !new Set(hiPaths).has(path));

    // Named in the failure rather than just counted: the point of the test is to say which string
    // to write, not that a number changed.
    expect(missing).toEqual([]);
  });

  it('has no Hindi string for a key English does not have', () => {
    // A leftover from a renamed key. Harmless at runtime and a slow drift into two different apps.
    const orphaned = hiPaths.filter((path) => !new Set(enPaths).has(path));

    expect(orphaned).toEqual([]);
  });

  it('leaves no Hindi value as a copy of the English one', () => {
    const enFlat = new Map(
      leafPaths(en as unknown as Node).map((p) => [p, resolve(en as unknown as Node, p)])
    );

    const untranslated = hiPaths.filter((path) => {
      const value = resolve(hi as unknown as Node, path);
      if (value === null) return false;

      // Deliberate exceptions: strings that are correct in Hindi *because* they are not Hindi.
      const SAME_BY_DESIGN = new Set([
        'settings.languageEnglish',
        'settings.languageHindi',
        'report.formatJson',
        'report.formatPdf',
        'report.formatDocx',
        'bulk.kindUrl',
        'context.quantityValuePlaceholder',
        'context.quantityUnitPlaceholder',
        'findings.zoom',
      ]);
      if (SAME_BY_DESIGN.has(path)) return false;

      return value === enFlat.get(path);
    });

    expect(untranslated).toEqual([]);
  });

  function resolve(node: Node, path: string): string | null {
    let current: unknown = node;
    for (const segment of path.split('.')) {
      if (typeof current !== 'object' || current === null) return null;
      current = (current as Node)[segment];
    }
    return typeof current === 'string' ? current : null;
  }
});

// ---------------------------------------------------------------- NFR-07 contrast

/** WCAG 2.1 relative luminance. */
function luminance(hex: string): number {
  const value = hex.replace('#', '');
  const channel = (offset: number) => {
    const raw = parseInt(value.slice(offset, offset + 2), 16) / 255;
    return raw <= 0.03928 ? raw / 12.92 : ((raw + 0.055) / 1.055) ** 2.4;
  };

  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

function contrast(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

describe('colour contrast', () => {
  /**
   * The foreground/background pairs the app actually draws.
   *
   * Written out rather than generated as a cross product: most combinations never occur, and a test
   * that fails on a pair nobody renders gets suppressed rather than fixed.
   */
  const PAIRS: [keyof typeof palettes.light, keyof typeof palettes.light][] = [
    ['text', 'bg'],
    ['text', 'surface'],
    ['text', 'surfaceAlt'],
    ['textMuted', 'bg'],
    ['textMuted', 'surface'],
    ['textMuted', 'surfaceAlt'],
    ['textSubtle', 'bg'],
    ['textSubtle', 'surface'],
    ['textSubtle', 'surfaceAlt'],
    ['brand', 'bg'],
    ['brand', 'surface'],
    ['brand', 'surfaceAlt'],
    ['brand', 'brandSoft'],
    ['onBrand', 'brand'],
    ['pass', 'surface'],
    ['pass', 'passSoft'],
    ['fail', 'surface'],
    ['fail', 'failSoft'],
    ['borderline', 'surface'],
    ['borderline', 'borderlineSoft'],
    ['notAssessable', 'surface'],
    ['notAssessable', 'notAssessableSoft'],
    ['warning', 'warningSoft'],
    ['info', 'infoSoft'],
  ];

  /**
   * 4.5:1, the normal-text threshold — not the 3:1 large-text allowance.
   *
   * `caption` is 12 px and `mono` is 13 px, and both carry real content: rule ids, millimetre
   * readings, hashes, the not-assessable reasons. None of that is large text, so none of it gets the
   * relaxed threshold.
   */
  const MIN_RATIO = 4.5;

  for (const scheme of ['light', 'dark'] as const) {
    describe(scheme, () => {
      for (const [fg, bg] of PAIRS) {
        it(`${fg} on ${bg} clears ${MIN_RATIO}:1`, () => {
          const palette = palettes[scheme];
          const ratio = contrast(palette[fg], palette[bg]);

          // The received value is in the message, so a failure says how far off it is.
          expect({ pair: `${fg}/${bg}`, ratio: Number(ratio.toFixed(2)) }).toEqual({
            pair: `${fg}/${bg}`,
            ratio: expect.any(Number),
          });
          expect(ratio).toBeGreaterThanOrEqual(MIN_RATIO);
        });
      }
    });
  }

  it('keeps the four verdict colours distinguishable from each other', () => {
    // Not a WCAG requirement, and the reason the verdicts do not rely on colour alone — every badge
    // carries its own label. But four verdicts rendered in four barely-different colours would make
    // a findings screen unreadable at a glance, which is the whole point of the grouping.
    for (const scheme of ['light', 'dark'] as const) {
      const p = palettes[scheme];
      const verdicts = [p.pass, p.fail, p.borderline, p.notAssessable];

      expect(new Set(verdicts).size).toBe(4);
    }
  });
});

// ---------------------------------------------------------------- the cutover property

describe('the mock is reachable from exactly two places', () => {
  const ROOT = join(__dirname, '..');

  function sourceFiles(dir: string): string[] {
    const out: string[] = [];

    const walk = (current: string) => {
      for (const entry of readdirSync(current)) {
        if (entry === 'node_modules' || entry.startsWith('.')) continue;
        const path = join(current, entry);
        if (statSync(path).isDirectory()) {
          walk(path);
          continue;
        }
        if (/\.tsx?$/.test(entry)) out.push(path);
      }
    };

    walk(dir);
    return out;
  }

  it('is imported by no app code except transport.ts and dev.ts', () => {
    const mockDir = join('src', 'api', 'mock');
    const allowed = [join('src', 'api', 'transport.ts'), join('src', 'api', 'dev.ts')];

    const offenders: string[] = [];

    for (const file of [...sourceFiles(join(ROOT, 'src')), ...sourceFiles(join(ROOT, 'app'))]) {
      const relative = file.slice(ROOT.length + 1);

      // The fixture layer may import itself.
      if (relative.startsWith(mockDir)) continue;
      if (allowed.includes(relative)) continue;

      const source = readFileSync(file, 'utf8');
      if (/from '@\/api\/mock|require\('\.\/mock|require\('\.\.\/mock/.test(source)) {
        offenders.push(relative);
      }
    }

    // A convenient `import { FIXTURE_OTP } from '@/api/mock'` in a screen is all it takes to put the
    // whole fixture graph back into the release bundle — `npm run verify:bundle` caught exactly that
    // before Stage 13. This is the cheap version of the same check.
    expect(offenders).toEqual([]);
  });

  it('reaches the mock only through a conditional require, never a static import', () => {
    for (const relative of ['src/api/transport.ts', 'src/api/dev.ts']) {
      const source = readFileSync(join(ROOT, relative), 'utf8');

      // A static *value* import is resolved by Metro whether or not the branch around it is
      // reachable, which is the trap this whole arrangement exists to avoid.
      //
      // `import type` is exempt, and that is not a loophole: Babel's TypeScript transform erases
      // type-only imports entirely, so Metro never sees them as dependencies. `dev.ts` uses two of
      // them for `FixtureAccount` and `Scenario`, and `npm run verify:bundle` confirms empirically
      // that neither pulls the fixtures into a live bundle.
      expect(source).not.toMatch(/^import (?!type )[^;]*from '\.\/mock/m);
      expect(source).toMatch(/require\('\.\/mock/);
    }
  });
});

// ---------------------------------------------------------------- NFR-02 instrument

describe('cold-start instrument', () => {
  afterEach(() => {
    resetStartupMeasurementForTests();
    delete (globalThis as { __BUNDLE_START_TIME__?: number }).__BUNDLE_START_TIME__;
  });

  it('reports nothing when there is no bundle start time to measure against', () => {
    // Under Jest there is no RN runtime, so this is the real state here. Returning `Date.now()`
    // instead would report a cold start of zero milliseconds, which is the kind of number that ends
    // up in a slide.
    expect(bundleStartTime()).toBeNull();
    expect(markFirstFrame()).toBeNull();
    expect(startupMeasurement()).toBeNull();
  });

  it('measures from bundle start to the marked frame', () => {
    (globalThis as { __BUNDLE_START_TIME__?: number }).__BUNDLE_START_TIME__ = 1_000;

    expect(markFirstFrame(3_400)).toEqual({ jsToFirstFrameMs: 2_400, measuredAt: 3_400 });
    expect(startupMeasurement()?.jsToFirstFrameMs).toBe(2_400);
  });

  it('keeps the first measurement, so a warm return cannot overwrite a cold start', () => {
    (globalThis as { __BUNDLE_START_TIME__?: number }).__BUNDLE_START_TIME__ = 1_000;

    markFirstFrame(3_400);
    markFirstFrame(9_999);

    expect(startupMeasurement()?.jsToFirstFrameMs).toBe(2_400);
  });

  it('refuses a negative or absurd interval rather than reporting it', () => {
    (globalThis as { __BUNDLE_START_TIME__?: number }).__BUNDLE_START_TIME__ = 10_000;

    // Clocks disagreeing is not a measurement.
    expect(markFirstFrame(9_000)).toBeNull();

    resetStartupMeasurementForTests();
    expect(markFirstFrame(10_000 + 200_000)).toBeNull();
  });

  it('judges against the NFR-02 budget', () => {
    expect(COLD_START_BUDGET_MS).toBe(3_000);
    expect(withinBudget({ jsToFirstFrameMs: 2_999 })).toBe(true);
    expect(withinBudget({ jsToFirstFrameMs: 3_000 })).toBe(true);
    expect(withinBudget({ jsToFirstFrameMs: 3_001 })).toBe(false);
  });
});
