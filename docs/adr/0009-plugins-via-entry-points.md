# Readers and VOD calculators from other packages are plugins, registered through entry points

A package adds a reader or a VOD calculator to `canvodpy run` by declaring
an entry point (`canvodpy.readers`, `canvodpy.vod_calculators`); the entry
point's name is the name in the settings and on the command line. Plugins
must inherit the abstract base class, and are imported and checked when
canvodpy is imported, so a broken plugin fails at once with its package's
name instead of in the middle of a run. A name that clashes with a
built-in or another plugin is an error, and `reader_format: auto` never
picks a plugin.

## Considered options

Registering classes in Python code (`ReaderFactory.register`) still works
inside one Python session, but cannot reach `canvodpy run`, which starts
its own process.
