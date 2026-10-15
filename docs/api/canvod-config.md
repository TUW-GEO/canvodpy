# `canvod.config` API reference

Settings: loading the settings file, Pydantic validation, and defaults.

## Loading

::: canvod.config
    options:
      members:
        - load_config
        - CanvodConfig
        - MetadataConfig
        - ProcessingConfig
        - SiteConfig
        - SitesConfig
        - SidsConfig

## Models

::: canvod.config.models
    options:
      members:
        - ProcessingParams
        - ReceiverConfig
        - PreprocessingConfig
        - TemporalAggregationConfig
        - GridAssignmentConfig
        - StorageConfig

## Setting help

What each setting means, from the descriptions on the models: the text of
`canvodpy config explain` and of the [Settings reference](../guides/settings.md).

::: canvod.config.settings_help
    options:
      members:
        - explain
        - find_setting
        - all_settings
        - SettingHelp
        - UnknownSettingError
