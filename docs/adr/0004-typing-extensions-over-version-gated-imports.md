# Backport 3.12-only typing via `typing_extensions`, not version-gated imports

**Decision:** `override` is imported from `typing_extensions` unconditionally, never gated on
`sys.version_info`, and `typing-extensions` is a declared **direct** runtime dependency rather than
a borrowed transitive one. The PEP 695 `type RedisClient = …` alias became a plain
`typing.TypeAlias` annotation, which needs no backport at all.

## Context

Lowering the supported-Python floor from 3.13 to 3.11 hit exactly two constructs that 3.11 cannot
parse or import: the PEP 695 `type` alias (a `SyntaxError` on 3.11) and `override` imported from
`typing` (an `ImportError` on 3.11, since it landed in 3.12). The alias had a stdlib answer —
`typing.TypeAlias` has existed since 3.10 — so only `override` needed a backport. Everything else
in the package was verified to work at the new floor: `typing.Self` and `datetime.UTC` both exist
in 3.11, and `datetime.UTC` is what fixes 3.11 as the floor rather than something lower.

Two alternatives were weighed for `override`:

- **`sys.version_info`-gated stdlib imports** — take `typing.override` on 3.12+ and the
  `typing_extensions` one below it. This is more code at every affected site, and it does not
  remove the dependency: 3.11 still needs `typing_extensions` installed, so the gate buys nothing
  beyond a marginally shorter import on newer interpreters.
- **Drop `@override` entirely** — the problem disappears if the package stops using it. Rejected:
  `@override` is what catches an override-mismatch against FastStream's base classes when upstream
  renames or re-signatures a method, which is precisely the failure this integration is exposed to.

## Decision & rationale

`typing_extensions` was already resolved transitively — FastStream pins `>=4.12.0`, and `override`
has been in `typing_extensions` since 4.4.0 — so declaring it directly costs nothing at install
time and makes the reliance explicit instead of borrowing a transitive pin that FastStream is free
to drop. The unconditional import is the simplest form that is correct on every supported
interpreter, and it keeps a single code path for `ty` to check rather than one path per interpreter
version.

**Revisit trigger:** the supported floor rises to 3.12 or above, at which point both constructs
have stdlib spellings on every supported interpreter and the direct `typing-extensions` dependency
can be dropped in the same change. A new 3.12+-only construct arriving before then is *not* a
revisit trigger — it takes the same `typing_extensions` treatment.
