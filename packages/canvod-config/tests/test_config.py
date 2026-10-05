#!/usr/bin/env python3
"""
Test script to verify configuration system imports and basic functionality.
Run this after installing canvod-utils to ensure everything works.
"""

import sys

print("Testing configuration system imports...")
print("=" * 70)

# Test imports
try:
    from canvod.config import load_config  # noqa: F401
    from canvod.config.models import (  # noqa: F401
        CanvodConfig,
        ProcessingConfig,
        SidsConfig,
        SitesConfig,
    )

    print("✓ All imports successful")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test model instantiation
try:
    from canvod.config.models import (
        AuxDataConfig,
        CredentialsConfig,
    )

    # Create test config with defaults
    creds = CredentialsConfig()
    assert creds.nasa_earthdata_acc_mail is None
    print("✓ Created CredentialsConfig with defaults (no email)")

    # Create test config with email
    creds = CredentialsConfig(
        nasa_earthdata_acc_mail="test@example.com",
    )
    print(f"✓ Created CredentialsConfig: {creds.nasa_earthdata_acc_mail}")

    aux_data = AuxDataConfig(agency="COD", product_type="final")
    print(f"✓ Created AuxDataConfig: {aux_data.agency}")

    # Test FTP server selection
    servers = aux_data.get_ftp_servers(creds.nasa_earthdata_acc_mail)
    print(f"✓ FTP servers (with email): {len(servers)} servers")
    for server, auth in servers:
        print(f"    - {server} (auth: {auth is not None})")

    servers_no_cddis = aux_data.get_ftp_servers(None)
    print(f"✓ FTP servers (without email): {len(servers_no_cddis)} servers")

except Exception as e:
    print(f"✗ Model test failed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("✓ All tests passed!")
print("\nNext steps:")
print("  1. Run: just config-init")
print("  2. Edit config/canvod-settings.yaml (processing:, sites:, sids:)")
print("  3. Run: just config-validate")
