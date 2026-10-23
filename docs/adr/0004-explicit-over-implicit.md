# Explicit over implicit: fail loudly, no hidden defaults

canvodpy's users are scientists who must be able to trust that a result
was computed the way they asked. A missing or wrong input stops with a
message that says what to do; nothing falls back silently. A default in a
signature or a documented settings model is visible and fine. Library code
reading the settings file behind the caller's back, or an `except` that
substitutes a value, is not: entry points (the command-line tool, `Site`) read the
settings and pass them down.
