import type { TieredResult } from '../../api/tiered';

// showplayer badge recipe: soft tinted fill + matching inset ring, no border.
export const TAG_BASE =
  'inline-flex items-center rounded px-[9px] py-0.5 text-xs font-semibold ring-1 ring-inset';

// Outlooks render as plain colored text, not pills.
export const DIRECTION_TEXT: Record<TieredResult['direction'], string> = {
  buy: 'text-emerald-300',
  hold: 'text-amber-300',
  sell: 'text-red-300',
  unknown: 'text-gray-400',
};

// Outlooks share the outlook palette: bullish = buy green, neutral =
// hold amber, bearish = sell red.
export const OUTLOOK_TEXT: Record<string, string> = {
  bullish: 'text-emerald-300',
  neutral: 'text-amber-300',
  bearish: 'text-red-300',
  unknown: 'text-gray-400',
};

// The showplayer pill palette (tagClassMap order, stone skipped by owner
// decision): colors are handed out to a section's fields in this fixed
// order (1, 2, 3, …), and a range's Min and Max share one color. Meaning
// does not pick the color — position does.
export const ALT_COLOR = {
  1: 'bg-red-500/20 text-red-300 ring-red-500/30',
  2: 'bg-orange-500/20 text-orange-300 ring-orange-500/30',
  3: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  4: 'bg-lime-500/20 text-lime-300 ring-lime-500/30',
  5: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  6: 'bg-sky-500/20 text-sky-300 ring-sky-500/30',
  7: 'bg-blue-500/20 text-blue-300 ring-blue-500/30',
  8: 'bg-indigo-500/20 text-indigo-300 ring-indigo-500/30',
  9: 'bg-violet-500/20 text-violet-300 ring-violet-500/30',
  gray: 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
} as const;

// The text color alone out of a pill tone, for a field title that turns
// the pill's color while a value is committed (owner request 2026-09-18):
// a colored title means "this filter is set", a gray one means it is not.
export const toneText = (tone: string): string =>
  tone.split(' ').find((token) => token.startsWith('text-')) ?? '';

// One line of a formula block (words / plugged-in / result): same element,
// font and spacing on every line, never wrapping. Colors match the shared
// modal contract in AltUi (body gray-300, emphasis gray-200 semibold).
export const FORMULA_LINE = 'whitespace-nowrap text-gray-300';
export const FORMULA_RESULT = 'whitespace-nowrap font-semibold text-gray-200';

// Inline text link, showplayer blue. The color utilities carry ! because
// index.css has an unlayered `a { color: inherit }` rule that outranks
// Tailwind's layered utilities on <a> tags — without !, every anchor link
// on this page silently renders in the surrounding text color.
export const ALT_LINK = 'text-blue-400! hover:text-blue-300! hover:underline';
