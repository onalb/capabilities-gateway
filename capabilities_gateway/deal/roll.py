"""Rent-roll shape stored by the deal app vault. Subset used by capability tools."""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, Field

_VACANT = re.compile(r"vacant|empty|down|model", re.I)
_OCCUPIED = re.compile(r"occup", re.I)


def parse_day(raw: object | None) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


class UnitRow(BaseModel):
    unit_id: str
    unit_type: str | None = None
    sqft: float | None = None
    occupancy: str | None = None
    in_place_rent: float = 0.0
    vacant: bool = False
    mtm: bool = False
    charge_codes: dict[str, float] = Field(default_factory=dict)
    lease_start: str | None = None
    lease_end: str | None = None

    def vacant_on(self, as_of: str | date | None) -> bool:
        occ = self.occupancy or ""
        if _VACANT.search(occ) and not _OCCUPIED.search(occ):
            return True
        if _OCCUPIED.search(occ):
            return False
        day = parse_day(as_of)
        start = parse_day(self.lease_start)
        end = parse_day(self.lease_end)
        if day and (start or end):
            if start and start > day:
                return True
            if end and end < day:
                return True
            if end and end >= day:
                return False
            if start and start <= day and end is None:
                return False
        return self.vacant


def mean_positive_sqft(units: list[UnitRow]) -> float | None:
    vals = [float(u.sqft) for u in units if u.sqft is not None and float(u.sqft) > 0]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


class CanonicalRentRoll(BaseModel):
    property_name: str | None = None
    as_of: str | None = None
    suggested_address: str | None = None
    geo_confidence: str = "medium"
    layout: str = "one_row"
    units: list[UnitRow] = Field(default_factory=list)
    source_filename: str | None = None

    @property
    def unit_count(self) -> int:
        return len(self.units)

    def vacant_count_on(self, as_of: str | date | None = None) -> int:
        return sum(1 for u in self.units if u.vacant_on(as_of or self.as_of))

    def occupied_count_on(self, as_of: str | date | None = None) -> int:
        return self.unit_count - self.vacant_count_on(as_of or self.as_of)

    def occupancy_pct_on(self, as_of: str | date | None = None) -> float:
        if not self.units:
            return 0.0
        return self.occupied_count_on(as_of) / self.unit_count

    @property
    def in_place_monthly(self) -> float:
        return self.in_place_monthly_on(self.as_of)

    def in_place_monthly_on(self, as_of: str | date | None = None) -> float:
        return sum(u.in_place_rent for u in self.units if not u.vacant_on(as_of or self.as_of))

    @property
    def mtm_count(self) -> int:
        return sum(1 for u in self.units if u.mtm)
