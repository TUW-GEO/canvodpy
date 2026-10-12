"""RINEX v3.05 stripped (SNR-only) observation reader.

Reads RINEX v3 files that have been stripped down to contain only signal
strength (S*) observables. Inherits from :class:`Rnxv3Obs` for header parsing,
epoch iteration, signal-ID mapping and dataset construction; it allocates
only the SNR array (no Pseudorange/Phase/Doppler/LLI/SSI), which is
significantly cheaper for the multi-hundred-MB daily files this format
typically produces.

Stripped files are recognized by their ``SYS / # / OBS TYPES`` records — every
observation code starts with ``S``. Files containing any non-SNR observable
are rejected with :class:`StrippedRinexError` at load time, since the full
:class:`Rnxv3Obs` reader is the right tool for those.
"""

from typing import Self

import xarray as xr
from pydantic import model_validator

from canvod.readers.rinex.v3_04 import (
    Rnxv3Obs,
)


class StrippedRinexError(ValueError):
    """Raised when a file is not a valid SNR-only stripped RINEX."""


class Rnxv3StrippedObs(Rnxv3Obs):
    """RINEX v3 reader for SNR-only stripped observation files.

    Stripped files contain only signal-strength (``S*``) observables — no
    pseudorange, carrier phase, or Doppler. This reader enforces that contract
    at load time and builds a Dataset with a single ``SNR`` data variable,
    skipping the auxiliary arrays that the full :class:`Rnxv3Obs` reader
    allocates.
    """

    @property
    def source_format(self) -> str:
        return "rinex3_stripped"

    @model_validator(mode="after")
    def _validate_snr_only(self) -> Self:
        bad: dict[str, list[str]] = {}
        for system, codes in self._header.obs_codes_per_system.items():
            non_snr = [c for c in codes if not c.startswith("S")]
            if non_snr:
                bad[system] = non_snr
        if bad:
            raise StrippedRinexError(
                f"File {self.fpath.name} is not a stripped RINEX: found "
                f"non-SNR observables {bad}. Use Rnxv3Obs for full files."
            )
        return self

    def _kept_vars(self, keep_data_vars: frozenset[str] | None) -> frozenset[str]:
        """Stripped files hold only SNR, so only SNR is ever allocated."""
        return super()._kept_vars(keep_data_vars) & {"SNR"}

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: object,
    ) -> xr.Dataset:
        """Convert the file to an (epoch, sid) dataset; see :meth:`Rnxv3Obs.to_ds`.

        ``keep_data_vars`` defaults to ``["SNR"]`` instead of the configured
        observables, since stripped files hold nothing else.
        """
        if keep_data_vars is None:
            keep_data_vars = ["SNR"]
        return super().to_ds(keep_data_vars=keep_data_vars, **kwargs)
