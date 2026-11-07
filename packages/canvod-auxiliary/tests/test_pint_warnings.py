"""canvod-auxiliary and canvod-readers share pint's application registry.

Both define ``dBHz`` in it; each must leave a definition the other made
alone (pint raises ``RedefinitionError`` on a second definition). Checked
in a fresh interpreter, as in a worker process.
"""

import subprocess
import sys


def test_both_unit_modules_import_together():
    code = (
        "import canvod.auxiliary._internal.units as a\n"
        "import canvod.readers.gnss_specs.constants as r\n"
        "assert a.UREG is r.UREG\n"
        "print(a.UREG.Quantity(1, 'dBHz').units)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "dBHz"
