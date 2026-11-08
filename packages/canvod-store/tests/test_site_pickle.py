"""A site travels to a worker process without its open stores (#433).

A run prepares its days in worker processes and sends them the site. The
stores a site has opened stay in the process that opened them; the copy
opens them again from their paths on first use.
"""

from __future__ import annotations

import pickle

from _helpers import new_gnss_store

from canvod.store.manager import GnssResearchSite
from canvod.utils import testing


def test_a_site_with_open_stores_pickles_without_them() -> None:
    site = GnssResearchSite(testing.SITE_KEY)
    new_gnss_store(site.gnss_store_path)
    opened = site.gnss_store

    copy = pickle.loads(pickle.dumps(site))

    assert copy.site_name == site.site_name
    assert copy.site_config == site.site_config
    assert "gnss_store" not in vars(copy)
    reopened = copy.gnss_store
    assert reopened is not opened
    assert reopened.store_path == opened.store_path
