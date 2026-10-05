import { describe, expect, test } from 'vitest';
import { evaluateArithmetic } from './safeArithmetic';

describe('evaluateArithmetic', () => {
  test('evaluates the back-of-envelope example from the task exactly', () => {
    // 500e6 * 0.1 * 5 / 86400
    expect(evaluateArithmetic('500e6 * 0.1 * 5 / 86400')).toBeCloseTo(2893.518518518519, 6);
  });

  test('respects operator precedence and parentheses', () => {
    expect(evaluateArithmetic('2 + 3 * 4')).toBe(14);
    expect(evaluateArithmetic('(2 + 3) * 4')).toBe(20);
  });

  test('supports unary minus and negative numbers', () => {
    expect(evaluateArithmetic('-5 + 3')).toBe(-2);
    expect(evaluateArithmetic('10 / -2')).toBe(-5);
  });

  test('supports scientific notation', () => {
    expect(evaluateArithmetic('1e3 + 1')).toBe(1001);
  });

  test('returns null for empty or non-arithmetic input, never throws', () => {
    expect(evaluateArithmetic('')).toBeNull();
    expect(evaluateArithmetic('   ')).toBeNull();
    expect(evaluateArithmetic('Assume 500M DAU')).toBeNull();
    expect(evaluateArithmetic('QPS = 100M / 86400')).toBeNull(); // "QPS =" isn't valid arithmetic
  });

  test('returns null on division by zero rather than Infinity/NaN', () => {
    expect(evaluateArithmetic('5 / 0')).toBeNull();
  });

  test('returns null for malformed expressions (unbalanced parens, trailing operator)', () => {
    expect(evaluateArithmetic('(2 + 3')).toBeNull();
    expect(evaluateArithmetic('2 +')).toBeNull();
    expect(evaluateArithmetic('2 3')).toBeNull();
  });

  test('never uses eval() or Function() on the input', () => {
    // A classic eval-injection probe — if this ever executed as JS instead of
    // being parsed as arithmetic, it would throw a ReferenceError (`window`
    // undefined in this environment) or return something other than null.
    expect(evaluateArithmetic('(() => 1)()')).toBeNull();
  });
});
