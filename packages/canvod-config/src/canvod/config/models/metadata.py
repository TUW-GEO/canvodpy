"""Metadata and credentials configuration models."""

from __future__ import annotations

from pydantic import EmailStr, Field, field_validator, model_validator

from .base import _StrictModel


class MetadataConfig(_StrictModel):
    """Metadata to be written to processed files.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    author: str = Field(
        ...,
        description=(
            "Your full name, used in dataset metadata and FAIR attribution "
            "(e.g. 'Jane Forester'). Wizard prompt: 'Who is running this pipeline?'"
        ),
    )
    email: EmailStr = Field(
        ...,
        description=(
            "Your contact email, included in DataCite and ACDD metadata records "
            "(e.g. 'jane@boku.ac.at'). Wizard prompt: 'Contact email address?'"
        ),
    )

    @field_validator("author", mode="before")
    @classmethod
    def _reject_sentinel_author(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() in {
            "Unknown",
            "Your Name",
            "Your Name Here",
        }:
            raise ValueError(
                f"author is set to placeholder {v!r}: "
                "fill in your real name in canvod-settings.yaml"
            )
        return v

    @field_validator("email", mode="before")
    @classmethod
    def _reject_sentinel_email(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() in {
            "user@example.com",
            "your@email.com",
            "your.email@example.com",
        }:
            raise ValueError(
                f"email is set to placeholder {v!r}: "
                "fill in your real email in canvod-settings.yaml"
            )
        return v

    orcid: str | None = Field(None, description="ORCID identifier")
    institution: str = Field(
        ...,
        description=(
            "Your institution or organization name "
            "(e.g. 'University of Natural Resources and Life Sciences Vienna'). "
            "Wizard prompt: 'Which institution do you belong to?'"
        ),
    )
    institution_ror: str | None = Field(None, description="ROR identifier")
    department: str | None = Field(None, description="Department name")
    research_group: str | None = Field(
        None,
        description="Research group name",
    )
    website: str | None = Field(
        None,
        description="Institution/group website",
    )
    license: str | None = Field(
        None,
        description=(
            "SPDX license identifier (e.g. 'CC-BY-4.0'), or 'other' for a "
            "license outside SPDX (then license_uri is required). Required "
            "when a store is created."
        ),
    )
    license_uri: str | None = Field(
        None,
        description="URI of the license text; required when license is 'other'",
    )
    publisher: str | None = Field(
        None, description="Publisher name. Required when a store is created."
    )
    publisher_url: str | None = Field(None, description="Publisher URL")
    naming_authority: str | None = Field(
        None,
        description=(
            "Your institution's domain in reverse order, lowercase "
            "(e.g. 'at.ac.tuwien'). Required when a store is created: with "
            "the store id it gives the store's id in the STAC catalog."
        ),
    )
    store_description: str | None = Field(
        None,
        description=(
            "Deprecated: one description for the stores of every site. Use "
            "sites.<name>.store_description instead."
        ),
    )
    initials: str | None = Field(
        None,
        description=(
            "How a store's metadata records who changed it (e.g. 'NFB'). "
            "Required to amend or migrate a store's metadata."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _warn_store_description(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("store_description") is not None:
            import warnings

            warnings.warn(
                "The setting 'processing.metadata.store_description' is left "
                "over from development and will be removed with the next major "
                "version: it gives the stores of every site the same "
                "description. Set 'store_description' on each site instead "
                "(sites.<name>.store_description).",
                FutureWarning,
                stacklevel=2,
            )
        return data

    def to_attrs_dict(self) -> dict[str, str]:
        """Convert to a dictionary for xarray attributes.

        Returns
        -------
        dict[str, str]
            Metadata as xarray-compatible attributes.
        """
        attrs = {
            "author": self.author,
            "email": self.email,
            "institution": self.institution,
        }
        if self.department:
            attrs["department"] = self.department
        if self.research_group:
            attrs["research_group"] = self.research_group
        if self.website:
            attrs["website"] = self.website
        return attrs


class CredentialsConfig(_StrictModel):
    """Credentials for external data services.

    Notes
    -----
    This is a Pydantic model for configuration validation.
    """

    nasa_earthdata_acc_mail: EmailStr | None = Field(
        None,
        description="NASA Earthdata email for CDDIS authentication (optional)",
    )
