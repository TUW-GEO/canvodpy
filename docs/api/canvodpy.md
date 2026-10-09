# canvodpy API Reference

Umbrella package for the canVODpy framework. One supported surface, plus the
CLI on top of it — see [API Levels](../guides/api-levels.md).

## Site and Pipeline (recommended — Python-native pipeline runs)

Stateful orchestrator with factory integration and structured logging. What
the CLI builds internally.

::: canvodpy.Site
::: canvodpy.Pipeline

## Factories

::: canvodpy.ReaderFactory
::: canvodpy.GridFactory
::: canvodpy.VODFactory

## Configuration

::: canvodpy.setup_logging
