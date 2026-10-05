// A tiny, safe arithmetic expression evaluator — deliberately NOT `eval()`
// or `new Function()` on user input. Supports +, -, *, /, parentheses, unary
// minus, and scientific notation (e.g. `500e6`), which covers the
// back-of-envelope-calculation use case (`500e6 * 0.1 * 5 / 86400`) without
// giving a text box the ability to run arbitrary JS.
//
// Recursive-descent parser over a hand-rolled tokenizer — standard shape,
// nothing clever: tokenize() -> a flat list of {type, value}, then
// parseExpression()/parseTerm()/parseFactor() implement the usual
// precedence climb (+/- loosest, then * //, then unary -, then parens/numbers).

const TOKEN_RE = /\s*(?:(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([+\-*/()]))/g;

function tokenize(expr) {
  const tokens = [];
  let lastIndex = 0;
  TOKEN_RE.lastIndex = 0;
  let m;
  while ((m = TOKEN_RE.exec(expr)) !== null) {
    if (m.index !== lastIndex) {
      throw new Error(`Unexpected character at position ${lastIndex}`);
    }
    if (m[1] !== undefined) tokens.push({ type: 'number', value: parseFloat(m[1]) });
    else if (m[2] !== undefined) tokens.push({ type: 'op', value: m[2] });
    lastIndex = TOKEN_RE.lastIndex;
  }
  if (lastIndex !== expr.length) {
    throw new Error(`Unexpected character at position ${lastIndex}`);
  }
  return tokens;
}

class Parser {
  constructor(tokens) {
    this.tokens = tokens;
    this.pos = 0;
  }
  peek() {
    return this.tokens[this.pos];
  }
  next() {
    return this.tokens[this.pos++];
  }
  parseExpression() {
    let value = this.parseTerm();
    while (this.peek() && (this.peek().value === '+' || this.peek().value === '-')) {
      const op = this.next().value;
      const rhs = this.parseTerm();
      value = op === '+' ? value + rhs : value - rhs;
    }
    return value;
  }
  parseTerm() {
    let value = this.parseUnary();
    while (this.peek() && (this.peek().value === '*' || this.peek().value === '/')) {
      const op = this.next().value;
      const rhs = this.parseUnary();
      if (op === '/' && rhs === 0) throw new Error('Division by zero');
      value = op === '*' ? value * rhs : value / rhs;
    }
    return value;
  }
  parseUnary() {
    if (this.peek() && this.peek().value === '-') {
      this.next();
      return -this.parseUnary();
    }
    if (this.peek() && this.peek().value === '+') {
      this.next();
      return this.parseUnary();
    }
    return this.parseFactor();
  }
  parseFactor() {
    const tok = this.peek();
    if (!tok) throw new Error('Unexpected end of expression');
    if (tok.type === 'number') {
      this.next();
      return tok.value;
    }
    if (tok.value === '(') {
      this.next();
      const value = this.parseExpression();
      if (!this.peek() || this.peek().value !== ')') throw new Error('Expected closing parenthesis');
      this.next();
      return value;
    }
    throw new Error(`Unexpected token: ${tok.value}`);
  }
}

/** Evaluates a plain arithmetic expression string safely (no eval/Function).
 * Returns a finite number on success, or `null` if the string isn't a valid
 * pure-arithmetic expression (so callers can silently skip non-math lines
 * of free-form notes instead of showing an error for every line typed). */
export function evaluateArithmetic(expr) {
  const trimmed = (expr || '').trim();
  if (!trimmed) return null;
  try {
    const tokens = tokenize(trimmed);
    if (tokens.length === 0) return null;
    const parser = new Parser(tokens);
    const value = parser.parseExpression();
    if (parser.pos !== tokens.length) return null; // trailing junk -> not pure arithmetic
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}
