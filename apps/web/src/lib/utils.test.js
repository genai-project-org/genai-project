import { describe, expect, test } from 'vitest';
import { cn } from './utils';

describe('cn', () => {
  test('joins truthy class names and drops falsy ones', () => {
    expect(cn('a', false && 'b', undefined, null, '', 'c')).toBe('a c');
  });

  test('merges conflicting tailwind utility classes, keeping the last one', () => {
    // twMerge should resolve conflicting padding utilities down to the last value
    expect(cn('p-2', 'p-4')).toBe('p-4');
  });

  test('supports conditional object/array inputs via clsx', () => {
    expect(cn('base', { active: true, hidden: false }, ['extra', null])).toBe('base active extra');
  });

  test('returns an empty string when given nothing usable', () => {
    expect(cn()).toBe('');
    expect(cn(false, null, undefined)).toBe('');
  });
});
