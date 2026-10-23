# The canopy and the reference receiver record the same file format

A site's canopy and reference receivers are always the same kind of
receiver writing the same format (both SBF, or both RINEX). Mixed setups
are not supported: loading such settings fails with an error, instead of
a run that silently reads one receiver with the other's reader.
