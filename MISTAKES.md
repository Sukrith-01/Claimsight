# Mistakes Log

One entry per real bug. Format: what broke → root cause → the category of
mistake, so the same class of error gets recognized faster next time.

This file starts empty. That's expected on Day 1 — it fills in as the
project hits real problems, which is the point of keeping it.

---

<!-- Example entry format, delete once the first real one lands:

## [Date] — Confidence scores all returned 0.0

**What broke:** every extracted field showed 0.0 confidence regardless of input.

**Root cause:** default value in Pydantic Field was mistakenly copied into
every response object as a *shared mutable default*.

**Category:** mutable default argument. Classic Python footgun — watch for
it anywhere a Field/dataclass default is a list, dict, or another model
instance instead of an immutable value.

-->
