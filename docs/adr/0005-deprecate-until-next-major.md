# Superseded public code is deprecated, and removed only with the next major version

v1.0.0 has one way to do each job, but users of earlier versions must not
break without warning. Code that a better path replaces gets the
`deprecated` decorator of canvod-utils: it warns with a `FutureWarning`
(shown by default, unlike `DeprecationWarning`), says it is left over from
development, names the replacement, and is removed in v2.0.0. Code that
does not belong in canvodpy at all is removed outright when the
maintainers decide so. The optional packages of canvodpy-extensions delete
leftover code instead of deprecating it.
