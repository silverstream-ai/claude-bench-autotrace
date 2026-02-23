**GENERAL RULES (Edicts)**

These are strict rules that must be followed.

**Offensive Programming**: How aggressively we fail depends on who owns the data:

- **Internal calls/APIs**: crash ASAP when something is wrong. It's better to crash loudly than to silently produce incorrect results.
- **External APIs we control**: surface errors loudly. If the data is broken or unexpected, complain — we own the contract and a violation is a bug we need to know about.
- **External APIs we don't control** (e.g. Claude Code hook event format): be lenient. Don't break if the format evolves.

**No unnecessary defaults**: We don't set variables to `null`, or `None`, or default values "just in case". At most points in the code, and especially for internal modules/APIs, we should be aware of what values _must_ and _can_ be set:
  - If a parameter is optional and is used only internally, the (internal) caller should just set it to `None` explicitly
  - If a parameter is _mandatory_ and has _no sensible default_, it shouldn't have a default value at all.

**Exceptions are rare**: `try/except` blocks should be uncommon. Only catch exceptions at system boundaries (user input, external APIs) or when you have a specific recovery strategy. Let errors propagate and crash.

**No unnecessary comments**: Don't use comments to explain what code does. Only use comments to document unexpected behavior, workarounds, or non-obvious "why" explanations. Code should be self-documenting through clear naming. This applies to docstrings too - don't add docstrings that just repeat what the function name says.

**Typing**: Use modern type hints only when necessary, e.g. `list[str]` not `List[str]`.

In a call stack, the value should be set only once, as high in the stack as possible.
Optional values are evil.


**Backend / Python files**

We use Python 3.12. All supported Python 3.12 features are available, and no features that depend on a higher python version should be used.

*** Type annotations ***

`mypy` provides typing checks: Hence, type annotations should be used wherever possible.

**** Casting `Any` values ****

Avoid using `cast`. If you _know_ that a `Any` variable is actually of type `T` _because of the code structure_, you can `assert` its type:

```
assert isinstance(my_var, T)
# Now mypy knows `my_var` is a T
```

*** Tests ***

All unit test cases for code living in file `path/to/file.py` should live in a file called `tests/path/to/test_file.py`.

There shouldn't be many exceptions to this: for bigger files, the size of the test file will grow a lot. When you feel uncomfortable with the number of unit test cases in a single python files, it's time to think: maybe the module being tested is the one that's too big in the first place, and we should split it :)

If a file _really_ needs to be big, and the test cases _can_ be semantically split into meaningful chunks, it's ok for the test path to be a directory. I.e. tests for `path/to/big_file.py` can live in `path/to/big_file/test_this.py`, `path/to/big_file/test_that.py`.

Each unit test case lives as a top-level function in the corresponding test case. I.e. do: `def test_case():`, don't do: `class TestCase:`.

When writing a unit test, the _only_ parts of the API under test that the test can access are the _public_ API. This means, _never ever_ attempt to read from a class's private fields: this is hard at times, but it's what makes the tests really useful. If you need to control side effects, ask yourself:
  - How does this side effect _reflect_ in the public API? If it doesn't, is it really a side effect worth testing?
  - If testing for resource leaks or similar, can I mock one of the DUT's dependencies instead, and test from there?

Prefer contract-focused tests over implementation-focused tests:
  - assert externally observable behavior (returned values, persisted artifacts, emitted outputs), not internal call ordering/details unless order is part of the contract.
  - keep tests minimal: fewer assertions with clear use-case intent are better than broad implementation snapshots.

Test doubles (mocks/fakes/stubs) should live near the runtime module, in `*_mocks.py` files (e.g. `foo_mocks.py`), and be imported by tests. Avoid defining large ad-hoc fake classes inline in test files when they can be shared.
