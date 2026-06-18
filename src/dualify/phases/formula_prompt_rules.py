"""Shared formula-writing rules for LLM extraction/repair prompts."""

REPAIR_FORMULA_RULES = """
Formula rules (must be SMT-compatible):
- Use explicit combinators: And(...), Or(...), Not(...), Implies(...), If(...).
- Quantifiers: ForAll([i], body) and Exists([i], body); every index variable must be bound.
- Allowed calls: And, Or, Not, Implies, If, ForAll, Exists, Abs, Length, Contains, PrefixOf,
  SuffixOf, Concat, Extract, Unit, floor, sqrt, pow, max, min, IsDigitString.
- Never use: Sum, Power, LessThan, all, any, comprehensions, lambdas, Python and/or/not, &, |.

Common mistakes to fix:
- postcondition must be ONE boolean formula over args and ret.
- Never set ret to a quantifier: `ret == ForAll(...)` / `ret == Exists(...)` is wrong when ret is
  int, float, str, list, or tuple. Put ForAll/Exists inside And/Or/Implies instead.
- Never pass a quantifier to Concat or other value operators:
  `ret == Concat(ForAll(...), ...)` is invalid. For reversed/copied strings use
  `ForAll([i], Implies(And(0 <= i, i < Length(side)), ret[i] == side[Length(side) - 1 - i]))`.
- No arithmetic on string characters: `src[i] + d` and `chars[i] + d` are invalid. Keep offsets as
  separate integers, e.g. Exists([d], And(0 <= d, d <= dist, src[k + i] == chars[i])) only when
  chars align; otherwise use a bounded Exists over matching positions without `+` on chars.
- Contains(seq, elem) requires elem to be a sequence element, not an integer index.
  For list/tuple membership use index quantifiers:
  `Exists([idx], And(0 <= idx, idx < Length(ret), ret[idx][0] == x, ret[idx][1] == y))`.
- Tuple returns: write `And(ret[0] == a, ret[1] == b)`, not `ret == (a, b)`.
- Optional / None: prefer `Length(ret) == 0` over `ret == None` for optional sequences;
  for optional tuple slots compare `ret[0]` / `ret[1]` directly with values or use If.
- String characters: compare with literal quotes, e.g. `expr[i] == '('`, not Python ord/char tricks.
- Division/modulo denominators must be guarded when they can be zero.
"""

SAFE_SUBSET_EXTRA_RULES = """
When unsure, prefer a weaker but valid formula over invalid syntax.
If exact behavior cannot be expressed in the safe subset, state a sound over-approximation in
postcondition (e.g. bounds, length, or simple equalities) rather than `ret == ret`.
"""
