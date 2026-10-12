"""Shared base class for all canvodpy config models."""

import difflib
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator
from pydantic_core import PydanticCustomError


class _StrictModel(BaseModel):
    """Base for all config models: forbids unknown keys so YAML typos are caught.

    An unknown key fails validation with the closest allowed key as a
    suggestion and the list of allowed keys. Nothing is corrected
    automatically: the settings file must be fixed.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="wrap")
    @classmethod
    def _suggest_unknown_keys(cls, data: Any, handler: Any) -> Any:
        try:
            return handler(data)
        except ValidationError as e:
            raise ValidationError.from_exception_data(
                e.title,
                [cls._error_details(err) for err in e.errors(include_url=False)],
            ) from None

    @classmethod
    def _error_details(cls, err: Any) -> Any:
        """Rebuild one error, keeping its message; name the right key if unknown.

        Errors of nested models already carry their own suggestion, so only
        an unknown key of this model (a one-element location) is rewritten.
        """
        error_type = PydanticCustomError(err["type"], err["msg"])
        if err["type"] == "extra_forbidden" and len(err["loc"]) == 1:
            key = str(err["loc"][0])
            allowed = list(cls.model_fields)
            match = difflib.get_close_matches(key, allowed, n=1)
            hint = f" Did you mean '{match[0]}'?" if match else ""
            error_type = PydanticCustomError(
                "extra_forbidden",
                "Unknown key '{key}'.{hint} Allowed keys: {allowed}",
                {"key": key, "hint": hint, "allowed": ", ".join(allowed)},
            )
        return {"type": error_type, "loc": err["loc"], "input": err["input"]}
