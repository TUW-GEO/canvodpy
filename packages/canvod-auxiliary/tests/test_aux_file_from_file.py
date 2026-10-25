"""``from_file`` reads the file it is given, of the product its name names."""

import shutil
from pathlib import Path

import pytest

from canvod.auxiliary.clock.reader import ClkFile
from canvod.auxiliary.ephemeris.reader import Sp3File
from canvod.auxiliary.products.registry_config import UnknownProductError

AUX = Path(__file__).parents[2] / "canvod-readers/tests/test_data/valid/aux_data"
SP3 = AUX / "01_SP3" / "COD0MGXFIN_20250010000_01D_05M_ORB.SP3"
CLK = AUX / "02_CLK" / "COD0MGXFIN_20250010000_01D_30S_CLK.CLK"

pytestmark = pytest.mark.skipif(
    not (SP3.exists() and CLK.exists()), reason="aux test data not available"
)


@pytest.mark.parametrize(
    ("cls", "src", "name", "agency", "product_type"),
    [
        (Sp3File, SP3, "COD0OPSRAP_20250010000_01D_05M_ORB.SP3", "COD", "rapid"),
        (ClkFile, CLK, "COD0OPSRAP_20250010000_01D_30S_CLK.CLK", "COD", "rapid"),
        (Sp3File, SP3, "USN0OPSRAP_20250010000_01D_15M_ORB.SP3", "USN", "rapid"),
        (Sp3File, SP3, "COD0MGXFIN_20250010000_01D_05M_ORB.SP3", "COD", "final"),
    ],
)
def test_reads_the_given_file_of_its_product(
    tmp_path, cls, src, name, agency, product_type
):
    fpath = tmp_path / name
    shutil.copy(src, fpath)

    aux = cls.from_file(fpath)

    assert (aux.agency, aux.product_type) == (agency, product_type)
    assert aux.fpath == fpath
    assert aux.data.sizes["epoch"] > 0
    assert [p.name for p in tmp_path.iterdir()] == [name]  # nothing downloaded


def test_a_file_of_no_registry_product_is_refused(tmp_path):
    fpath = tmp_path / "XYZ0OPSRAP_20250010000_01D_05M_ORB.SP3"
    shutil.copy(SP3, fpath)
    with pytest.raises(UnknownProductError, match="XYZ0OPSRAP"):
        Sp3File.from_file(fpath)
