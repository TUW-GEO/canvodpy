"""Made-up data for tests, from Tolkien's Middle-earth.

Tests never use real people or real research sites. When a test needs a
person, a site or a position, it takes them from here:

    from canvod.utils import testing

    meta = Creator(name=testing.PERSON_NAME, email=testing.PERSON_EMAIL, ...)

The position is Tolkien's birthplace, Bloemfontein.
"""

from __future__ import annotations

#: The person who runs the made-up site.
PERSON_NAME = "John Ronald Reuel Tolkien"
#: How the person signs changes of store metadata.
PERSON_INITIALS = "JRRT"
PERSON_EMAIL = "j.r.r.tolkien@the.inklings.org"
INSTITUTION = "University of Oxford"
DEPARTMENT = "English Faculty"
RESEARCH_GROUP = "The Inklings"
PUBLISHER = "The Inklings"
WEBSITE = "https://the.inklings.org"
#: A made-up software repository and its documentation.
REPOSITORY = "https://github.com/the-inklings/red-book"
DOCUMENTATION = "https://github.com/the-inklings/red-book/tree/main/docs"
#: A valid naming authority (reverse DNS).
NAMING_AUTHORITY = "org.middle-earth"

#: The site as a key of the settings (``sites.fangorn``) and in store ids.
SITE_KEY = "fangorn"
#: The site in file names: 3-letter site ID and 3-letter agency of the
#: canVOD file name convention (``FANA01INK_R_...`` for a canopy receiver).
SITE_ID = "FAN"
AGENCY = "INK"
#: A second site for file names (``ORTA01MEA_R_...``).
OTHER_SITE_ID = "ORT"
OTHER_AGENCY = "MEA"

#: The below-canopy site or receiver.
CANOPY_SITE = "Fangorn"
#: The reference (open sky) site or receiver.
REFERENCE_SITE = "Orthanc"
#: The tree species below which the canopy receiver sits.
SPECIES = "Ent"
#: The canopy site's description, Gandalf in The Two Towers.
SITE_DESCRIPTION = (
    "Certainly the forest of Fangorn is perilous — not least to those that "
    "are too ready with their axes; and Fangorn himself, he is perilous "
    "too; yet he is wise and kindly nonetheless. But now his long slow "
    "wrath is brimming over, and all the forest is filled with it."
)

#: Bloemfontein: WGS84 decimal degrees, and its elevation in meters
#: (approximate).
LATITUDE = -29.12
LONGITUDE = 26.21
ALTITUDE_M = 1395.0

#: The same position in WGS84 ECEF (meters), taking ALTITUDE_M as the height
#: above the ellipsoid. From PROJ (pyproj, EPSG:4979 to EPSG:4978) and the
#: closed-form WGS84 formula, which agree to the millimeter.
ECEF_X = 5004115.301
ECEF_Y = 2463414.934
ECEF_Z = -3086206.104
