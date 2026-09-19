# Backport 3.12-only typing via `typing_extensions`, not version-gated imports

Lowering the supported floor from 3.13 to 3.11 broke exactly two constructs: the PEP 695
`type RedisClient = ...` alias, a `SyntaxError` on 3.11, and `override` imported from `typing`,
which landed in 3.12. The alias became a plain `typing.TypeAlias` annotation, which needs no
backport; `override` is imported from `typing_extensions` unconditionally, never gated on
`sys.version_info`, and `typing-extensions` is a declared direct runtime dependency rather than a
pin borrowed from FastStream, which is free to drop it. A `sys.version_info` gate was rejected
because 3.11 needs the package installed either way, so it buys only more code at every affected
site and a second path for `ty` to check. Dropping `@override` was rejected because it is what
catches a signature drift against FastStream's base classes, precisely the failure this integration
is exposed to. When the floor rises to 3.12 both constructs gain stdlib spellings and the direct
dependency goes with them.
