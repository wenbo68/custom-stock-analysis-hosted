import type { TieredCitation, TieredResult } from '../../api/tiered';

export const DIRECTION_BADGE: Record<
  TieredResult['direction'],
  'success' | 'warning' | 'danger' | 'default'
> = {
  buy: 'success',
  hold: 'warning',
  sell: 'danger',
  unknown: 'default',
};

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'number') {
    const abs = Math.abs(value);
    if (abs >= 1e12) {
      return `${(value / 1e12).toFixed(2)} trillion`;
    }
    if (abs >= 1e9) {
      return `${(value / 1e9).toFixed(2)} billion`;
    }
    if (abs >= 1e6) {
      return `${(value / 1e6).toFixed(2)} million`;
    }
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—';
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

// Old stored runs may hold one citation per quote (several per source);
// collapse to one entry per source so numbering matches inline [n] marks.
export function dedupeCitations(citations: TieredCitation[]): TieredCitation[] {
  return citations.filter(
    (citation, index, all) =>
      all.findIndex(
        (other) => (other.url || other.source_name) === (citation.url || citation.source_name),
      ) === index,
  );
}

// Payload rows carry ids of this shape so evidence references
// ("technicals.sma_20", "fundamentals.valuation.pe_ttm") can anchor-jump
// to the exact row on the dimension card.
export function metricAnchorId(refPath: string): string {
  return `tiered-metric-${refPath.replace(/\./g, '-')}`;
}

const FLASH_CLASSES = ['ring-2', 'ring-cyan', 'rounded-md'];
const FLASH_DURATION_MS = 1800;

// Scroll to any element by id and flash it — the metric jump, generalized
// so other in-report links (e.g. the shares-computation numbers) can
// anchor-jump the same way.
export function flashElement(id: string): boolean {
  const element = document.getElementById(id);
  if (!element) {
    return false;
  }
  element.scrollIntoView({ behavior: 'smooth', block: 'center' });
  element.classList.add(...FLASH_CLASSES);
  window.setTimeout(() => element.classList.remove(...FLASH_CLASSES), FLASH_DURATION_MS);
  return true;
}

export function jumpToMetric(refPath: string): boolean {
  return flashElement(metricAnchorId(refPath));
}

// Jump to the first path that exists on the page. Warning sentences use
// this to point at a metric whose payload path moved across payload
// versions (e.g. technicals.atr_14 → technicals.volatility.atr_14): the
// stored run decides which row exists, so trying in order is exact.
export function jumpToMetricFirst(refPaths: string[]): boolean {
  return refPaths.some((refPath) => jumpToMetric(refPath));
}

// The v2 payloads wrap every metric as {name, explanation, value} —
// runs from 2026-07-29 on add an "interpretation" key (how to read the
// number) — so the LLM and API consumers read what a number means. The
// UI unwraps to the value and keeps its own i18n labels (metricLabels).
export interface MetricEnvelope {
  name: string;
  explanation: string;
  interpretation?: string;
  value: unknown;
}

const ENVELOPE_REQUIRED = ['explanation', 'name', 'value'];
const ENVELOPE_OPTIONAL = ['interpretation'];

export function isMetricEnvelope(node: unknown): node is MetricEnvelope {
  if (node === null || typeof node !== 'object' || Array.isArray(node)) {
    return false;
  }
  const keys = Object.keys(node as Record<string, unknown>);
  return (
    ENVELOPE_REQUIRED.every((key) => keys.includes(key)) &&
    keys.every(
      (key) => ENVELOPE_REQUIRED.includes(key) || ENVELOPE_OPTIONAL.includes(key),
    )
  );
}

export function metricValue(node: unknown): unknown {
  return isMetricEnvelope(node) ? node.value : node;
}
