"""Check the product registry against the files on its FTP servers.

For each day, every server's GPS-week directory is listed once, and each
registry product is looked up in the listings: its SP3 file, and its CLK file
if it publishes clocks, under any of the samplings the registry names. A
product passes for a day if one server has its files.

Run it with ``just check-products [YYYYDOY ...]`` or::

    python -m canvod.auxiliary.products.check 2025001 --cddis-mail you@example.org

Without ``--cddis-mail`` only the servers that need no account (ESA) are
checked.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from ftplib import FTP, FTP_TLS
from urllib.parse import urlparse

from canvod.utils.tools import YYYYDOY

from canvod.auxiliary.products.registry_config import ProductSpec, get_registry

#: Lists one directory of one server: ``(server_url, path) -> file names``.
DirLister = Callable[[str, str], set[str]]


@dataclass
class ProductDayCheck:
    """Registry files of one product for one day, as found on the servers."""

    product: str
    day: str
    sp3: str | None = None
    clk: str | None = None
    has_clock: bool = True
    servers: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    #: No server checked: all need an account and none was given.
    skipped: bool = False

    @property
    def ok(self) -> bool:
        """SP3 found, and CLK too if the product publishes clocks."""
        return self.sp3 is not None and (self.clk is not None or not self.has_clock)


def ftp_lister(cddis_mail: str | None, timeout_s: int = 120) -> DirLister:
    """Directory lister for ``ftp://`` (anonymous) and ``ftps://`` servers.

    Parameters
    ----------
    cddis_mail : str | None
        Password for the anonymous FTPS login of NASA CDDIS.
    timeout_s : int
        Connection timeout in seconds.

    Returns
    -------
    DirLister
        Lister returning the file names of a directory.
    """

    def list_dir(server_url: str, path: str) -> set[str]:
        url = urlparse(server_url)
        if url.scheme == "ftps":
            ftps = FTP_TLS(host=url.hostname or "", timeout=timeout_s)
            ftps.login(user="anonymous", passwd=cddis_mail or "")
            ftps.prot_p()
            ftp: FTP = ftps
        else:
            ftp = FTP(host=url.hostname or "", timeout=timeout_s)
            ftp.login()
        try:
            return {name.rsplit("/", 1)[-1] for name in ftp.nlst(path)}
        finally:
            ftp.quit()

    return list_dir


def _servers(spec: ProductSpec, with_auth: bool) -> list[str]:
    servers = sorted(spec.ftp_servers, key=lambda s: s.priority)
    return [s.url for s in servers if with_auth or not s.requires_auth]


def check_registry(
    days: Iterable[str],
    list_dir: DirLister,
    with_auth: bool,
    products: Iterable[ProductSpec] | None = None,
) -> list[ProductDayCheck]:
    """Look up every registry product's files in the server listings.

    Parameters
    ----------
    days : Iterable[str]
        Days as ``YYYYDOY``.
    list_dir : DirLister
        Lists one directory of one server.
    with_auth : bool
        Also check servers that need an account (NASA CDDIS).
    products : Iterable[ProductSpec], optional
        Products to check; default: the whole registry.

    Returns
    -------
    list[ProductDayCheck]
        One result per product and day.
    """
    registry = get_registry()
    if products is None:
        products = [registry.get_product_spec(*key) for key in registry.list_products()]
    products = list(products)

    listings: dict[tuple[str, str], set[str]] = {}
    results = []
    for day in days:
        week = str(YYYYDOY.from_str(day).gps_week)
        for spec in products:
            result = ProductDayCheck(
                f"{spec.agency_code}/{spec.product_type}",
                day,
                has_clock=spec.has_clock,
            )
            servers = _servers(spec, with_auth)
            result.skipped = not servers
            for server in servers:
                path = spec.ftp_path_pattern.format(gps_week=week, file="")
                key = (server, path)
                if key not in listings:
                    listings[key] = list_dir(server, path)
                names = listings[key]
                sp3 = next(
                    (n for n in spec.sp3_filenames(day) if f"{n}.gz" in names), None
                )
                clk = next(
                    (n for n in spec.clk_filenames(day) if f"{n}.gz" in names), None
                )
                if sp3 and (clk or not spec.has_clock):
                    result.sp3, result.clk = sp3, clk
                    result.servers.append(server)
                result.present = sorted(
                    set(result.present)
                    | {
                        n.removesuffix(".gz")
                        for n in names
                        if n.startswith(f"{spec.prefix}_{day}")
                        and ("_ORB.SP3" in n or "_CLK.CLK" in n)
                    }
                )
            results.append(result)
    return results


def _default_days() -> list[str]:
    """2025-001 (the test data) and a day three weeks ago (finals are out)."""
    recent = datetime.date.today() - datetime.timedelta(days=21)
    return ["2025001", YYYYDOY.from_date(recent).to_str()]


def main(argv: list[str] | None = None) -> int:
    """Print the check of every registry product; 1 if any product fails."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("days", nargs="*", help="Days as YYYYDOY")
    parser.add_argument("--cddis-mail", help="NASA Earthdata e-mail (checks CDDIS)")
    args = parser.parse_args(argv)
    days = args.days or _default_days()

    results = check_registry(
        days, ftp_lister(args.cddis_mail), with_auth=bool(args.cddis_mail)
    )
    if not args.cddis_mail:
        print("NASA CDDIS not checked (no --cddis-mail).\n")
    for r in results:
        if r.skipped:
            print(f"skipped  {r.product:12} {r.day}  only on servers with login")
        elif r.ok:
            clk = r.clk or "no clocks"
            hosts = ", ".join(urlparse(s).hostname or s for s in r.servers)
            print(f"ok       {r.product:12} {r.day}  {r.sp3}  {clk}  ({hosts})")
        else:
            present = ", ".join(r.present) or "no SP3/CLK file of this product"
            print(f"MISSING  {r.product:12} {r.day}  on the servers: {present}")
    failed = [r for r in results if not r.ok and not r.skipped]
    checked = [r for r in results if not r.skipped]
    print(f"\n{len(checked) - len(failed)} of {len(checked)} product-days found.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
