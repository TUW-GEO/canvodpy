# `canvod.auxiliary` API reference

SP3 ephemeris and CLK clock correction processing, interpolation, coordinate
transformations, and the GNSS product registry.

## Package

::: canvod.auxiliary
    options:
      members:
        - Sp3File
        - ClkFile
        - AuxFile
        - Interpolator
        - InterpolatorConfig
        - DatasetMatcher
        - ECEFPosition
        - GeodeticPosition

## Preprocessing

::: canvod.auxiliary.preprocessing

## Interpolation

::: canvod.auxiliary.interpolation

## Ephemeris (SP3)

::: canvod.auxiliary.ephemeris

## Clock (CLK)

Optional: only when `aux_data.fetch_clock` is `true` (the default); the VOD
formula doesn't use them. Set it to `false` to skip downloading, reading and
interpolating clock files.

::: canvod.auxiliary.clock

## Position and coordinates

::: canvod.auxiliary.position

## Product registry

::: canvod.auxiliary.products
    options:
      members:
        - PRODUCT_REGISTRY
        - ProductSpec
        - get_product_spec
        - list_available_products
        - list_agencies
        - get_products_for_agency
