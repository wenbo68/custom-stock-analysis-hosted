import { describe, expect, it } from 'vitest';
import { UI_TEXT, formatUiText, type UiTextKey } from '../uiText';

// A key present in one language and absent in the other is invisible to
// TypeScript (both dictionaries are plain records) and to every component
// test that renders only one language. It surfaces at RUNTIME as
// "Cannot read properties of undefined (reading 'replace')" inside
// formatUiText — which is how a title key deleted during the 2026-08-08
// modal rework took down the legacy /tiered page while the whole alt-page
// suite stayed green.
describe('UI_TEXT — the two languages stay in step', () => {
  const en = Object.keys(UI_TEXT.en) as UiTextKey[];
  const zh = Object.keys(UI_TEXT.zh) as UiTextKey[];

  it('every English key has a Chinese one', () => {
    expect(en.filter((key) => !(key in UI_TEXT.zh))).toEqual([]);
  });

  it('every Chinese key has an English one', () => {
    expect(zh.filter((key) => !(key in UI_TEXT.en))).toEqual([]);
  });

  it('no entry is an empty string in either language', () => {
    const blank = en.filter(
      (key) => !UI_TEXT.en[key]?.trim() || !UI_TEXT.zh[key]?.trim(),
    );
    expect(blank).toEqual([]);
  });

  it('a placeholder in one language appears in the other', () => {
    // "{label}" in English but not in Chinese means the Chinese string
    // silently drops the value it was meant to interpolate.
    const slots = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const mismatched = en.filter(
      (key) => slots(UI_TEXT.en[key]).join() !== slots(UI_TEXT.zh[key]).join(),
    );
    expect(mismatched).toEqual([]);
  });

  it('formatUiText fills a slot and leaves unknown ones alone', () => {
    expect(formatUiText('{a} and {b}', { a: 'x' })).toBe('x and {b}');
  });
});
