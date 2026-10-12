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
PUBLISHER = "The Inklings"
#: A valid naming authority (reverse DNS).
NAMING_AUTHORITY = "org.middle-earth"

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

#: Bloemfontein: WGS84 decimal degrees, and its elevation in metres
#: (approximate).
LATITUDE = -29.12
LONGITUDE = 26.21
ALTITUDE_M = 1395.0
