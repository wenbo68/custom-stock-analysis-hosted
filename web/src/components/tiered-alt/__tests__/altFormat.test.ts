import { describe, expect, it } from 'vitest';
import { queuePosition } from '../altFormat';

describe('queuePosition', () => {
  it('turns the count ahead into an English ordinal position', () => {
    expect(queuePosition(0, 'en')).toBe('1st');
    expect(queuePosition(1, 'en')).toBe('2nd');
    expect(queuePosition(2, 'en')).toBe('3rd');
    expect(queuePosition(3, 'en')).toBe('4th');
    // 11th-13th keep "th"; 21st, 22nd and 23rd go back to the short endings
    expect(queuePosition(10, 'en')).toBe('11th');
    expect(queuePosition(11, 'en')).toBe('12th');
    expect(queuePosition(12, 'en')).toBe('13th');
    expect(queuePosition(20, 'en')).toBe('21st');
    expect(queuePosition(21, 'en')).toBe('22nd');
    expect(queuePosition(22, 'en')).toBe('23rd');
    expect(queuePosition(110, 'en')).toBe('111th');
  });

  it('writes the position in Chinese', () => {
    expect(queuePosition(0, 'zh')).toBe('第 1 位');
    expect(queuePosition(2, 'zh')).toBe('第 3 位');
  });
});
