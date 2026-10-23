"""Publication and funding reference models."""

from __future__ import annotations

from pydantic import Field

from .base import _StrictModel


class PublicationRef(_StrictModel):
    """A publication reference."""

    doi: str = Field(..., description="DOI of the publication")
    citation: str | None = Field(None, description="Citation of the publication")


class FundingRef(_StrictModel):
    """A funding reference."""

    funder: str = Field(..., description="Name of the funding organization")
    funder_ror: str | None = Field(
        None, description="ROR identifier of the funding organization"
    )
    grant_number: str | None = Field(None, description="Grant number")
    award_title: str | None = Field(None, description="Title of the grant")


class ReferencesConfig(_StrictModel):
    """Publications, funding, and related-resource references."""

    software_repository: str | None = Field(
        None, description="URL of the software repository (for example GitHub)"
    )
    documentation: str | None = Field(None, description="URL of the documentation")
    access_url: str | None = Field(
        None,
        description="URL where the store data is actually accessible (FAIR A1)",
    )
    related_stores: list[str] = Field(
        default_factory=list, description="Identifiers/paths of related stores"
    )
    publications: list[PublicationRef] = Field(
        default_factory=list,
        description="Publications about the data, for the store metadata",
    )
    funding: list[FundingRef] = Field(
        default_factory=list,
        description="Funding of the work, for the store metadata",
    )
