/**
 * Rule metadata, transcribed verbatim from `rulepacks/lm-2011-v1.yaml`.
 *
 * This exists so fixture findings cite the **real** rule ids, severities and legal citations
 * rather than plausible-looking inventions. A demo that shows `Rule 9(2)(i) read with Table-I`
 * next to a measured millimetre value is defensible in front of a judge; one that shows
 * `RULE_123` is not.
 *
 * It is a mirror, not a source. The rule pack is the source, the backend loads it, and this file
 * disappears with the rest of the mock at Stage 13. Do not add a rule here that is not in the
 * pack, and do not change a citation here without changing it there — rule text has legal
 * consequences and needs review (CLAUDE.md §7).
 */

import type { Severity } from '@/domain';

export const RULEPACK_VERSION = 'LM-2011-v1.0';

export interface RuleMeta {
  severity: Severity;
  citation: string;
  message: string;
}

export const RULES = {
  'LM-6-1-A-MANUFACTURER': {
    severity: 'major',
    citation: 'Rule 6(1)(a), Legal Metrology (Packaged Commodities) Rules, 2011',
    message: 'Name and complete address of the manufacturer/packer must appear on the package.',
  },
  'LM-6-1-IMPORTER': {
    severity: 'major',
    citation: 'Rule 6(1)(a) proviso, LMPC Rules, 2011',
    message:
      'Imported packages must declare the name and complete address of the importer in India.',
  },
  'LM-6-1-B-COMMON-NAME': {
    severity: 'major',
    citation: 'Rule 6(1)(b), LMPC Rules, 2011',
    message: 'The common or generic name of the commodity must be declared.',
  },
  'LM-6-1-D-NET-QUANTITY': {
    severity: 'critical',
    citation: 'Rule 6(1)(d), LMPC Rules, 2011',
    message: 'Net quantity must be declared in standard units.',
  },
  'LM-6-1-C-MFG-DATE': {
    severity: 'major',
    citation: 'Rule 6(1)(c), LMPC Rules, 2011',
    message: 'Month and year of manufacture/packing/import must be declared.',
  },
  'LM-6-1-E-MRP': {
    severity: 'critical',
    citation: 'Rule 6(1)(e), LMPC Rules, 2011',
    message: 'Retail sale price must be declared.',
  },
  'LM-6-1-F-CONSUMER-CARE': {
    severity: 'major',
    citation: 'Rule 6(1)(f), LMPC Rules, 2011',
    message:
      'Consumer care details, including a name and at least one contact channel, must be declared.',
  },
  'LM-MRP-INCLUSIVE-WORDING': {
    severity: 'major',
    citation: 'Rule 6(1)(e) read with Rule 18, LMPC Rules, 2011',
    message: 'Retail sale price must be expressed as inclusive of all taxes.',
  },
  'LM-QTY-UNIT-SYMBOL': {
    severity: 'minor',
    citation: 'Rule 8 read with the Second Schedule, LMPC Rules, 2011',
    message: "Net quantity must use the prescribed unit symbol (e.g. 'g', not 'gms').",
  },
  'LM-MFG-DATE-FORMAT': {
    severity: 'minor',
    citation: 'Rule 6(1)(c), LMPC Rules, 2011',
    message: "Month and year of manufacture must be resolvable (e.g. '03/2026' or 'MAR 2026').",
  },
  'LM-9-2-TABLE1': {
    severity: 'major',
    citation:
      'Rule 9(2)(i) read with Table-I, LMPC Rules, 2011 (as substituted by G.S.R. 629(E) dated 23.06.2017)',
    message: 'Numeral height in the net quantity declaration must meet the Table-I minimum.',
  },
  'LM-9-2-TABLE2': {
    severity: 'major',
    citation: 'Rule 9(2)(ii) read with Table-II, LMPC Rules, 2011',
    message: 'Numeral height must meet the Table-II minimum for the principal display panel area.',
  },
  'LM-9-LETTER-HEIGHT': {
    severity: 'major',
    citation: 'Rule 9(3), LMPC Rules, 2011 (as substituted by G.S.R. 629(E) dated 23.06.2017)',
    message: 'Letter height in a declaration must meet the minimum.',
  },
  'LM-9-3-WIDTH': {
    severity: 'minor',
    citation: 'Rule 9(3) proviso, LMPC Rules, 2011',
    message: 'Glyph width must be at least one third of its height.',
  },
  'LM-9-QTY-CLEAR-SPACE': {
    severity: 'minor',
    citation: 'Rule 9(1) proviso, LMPC Rules, 2011',
    message:
      'The area surrounding the net quantity declaration must be free from other printed information.',
  },
  'LM-6-10A-COO-FILTER': {
    severity: 'major',
    citation:
      'Rule 6(10A), LMPC Rules, 2011 (G.S.R. 128(E) dated 13.02.2026, as substituted by the Second Amendment Rules, 2026; effective 01.07.2027)',
    message:
      'E-commerce listings of imported products must provide a searchable and sortable country-of-origin filter.',
  },
} as const satisfies Record<string, RuleMeta>;

export type RuleId = keyof typeof RULES;

export const RULE_IDS = Object.keys(RULES) as RuleId[];
