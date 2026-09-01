"""Bank profile loading and validation.

A bank profile biases the (otherwise uniform) mock data generator toward a
realistic funding shape for a specific institution. Profiles are authored by an
LLM (see tools/generate_profiles.py) but are always validated against the
FR 2052a schema before use, so any hallucinated product / counterparty /
collateral value is dropped rather than emitted.

Profile JSON format
-------------------
{
  "bank": "Wells",
  "description": "free text",
  "table_weights":    { "<prefix>": <float>, ... },   # e.g. "O.D": 3.0
  "product_weights":  { "<product_id>": <float>, ... },# e.g. "O.D.1": 4.0
  "amount_scale":     { "<prefix>": <float>, ... },    # multiplier on amounts
  "counterparty_distribution": {
      "<prefix>": { "<Counterparty>": <float>, ... }
  },
  "collateral_distribution": {
      "<prefix>": { "<CollateralClass>": <float>, ... }
  }
}

All sections are optional. Unknown keys are ignored; unknown references are
dropped during validation and recorded in ``ProfileValidation.warnings``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .schema_loader import Schema


@dataclass
class BankProfile:
    bank: str
    description: str = ""
    table_weights: dict[str, float] = field(default_factory=dict)
    product_weights: dict[str, float] = field(default_factory=dict)
    amount_scale: dict[str, float] = field(default_factory=dict)
    counterparty_distribution: dict[str, dict[str, float]] = field(default_factory=dict)
    collateral_distribution: dict[str, dict[str, float]] = field(default_factory=dict)

    # --- lookups used by the generator ---------------------------------------
    def product_weight(self, product_id: str, prefix: str) -> float:
        if product_id in self.product_weights:
            return self.product_weights[product_id]
        return self.table_weights.get(prefix, 1.0)

    def amount_multiplier(self, prefix: str) -> float:
        return self.amount_scale.get(prefix, 1.0)

    def counterparty_weights(self, prefix: str) -> dict[str, float] | None:
        return self.counterparty_distribution.get(prefix) or None

    def collateral_weights(self, prefix: str) -> dict[str, float] | None:
        return self.collateral_distribution.get(prefix) or None


@dataclass
class ProfileValidation:
    profile: BankProfile
    warnings: list[str] = field(default_factory=list)


class ProfileError(ValueError):
    """Raised when a profile file is missing or fundamentally malformed."""


def _coerce_weight_map(raw: object, positive: bool = True) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if positive and fv < 0:
            continue
        out[str(k)] = fv
    return out


def validate_profile(raw: dict, schema: Schema) -> ProfileValidation:
    """Validate ``raw`` profile data against ``schema``.

    Unknown product IDs, table prefixes, counterparty values, and collateral
    classes are dropped and reported as warnings. Returns a cleaned
    :class:`BankProfile`.
    """
    warnings: list[str] = []

    valid_prefixes = {t.prefix for t in schema.tables}
    valid_products = {p.id for _, p in schema.all_products()}
    valid_counterparties = set(schema.enum_values("Counterparty"))
    valid_collateral = set(schema.enum_values("CollateralClass"))

    bank = str(raw.get("bank", "")).strip()
    if not bank:
        raise ProfileError("Profile is missing required 'bank' field")

    # table_weights
    table_weights = {}
    for prefix, w in _coerce_weight_map(raw.get("table_weights")).items():
        if prefix in valid_prefixes:
            table_weights[prefix] = w
        else:
            warnings.append(f"Dropped unknown table prefix in table_weights: '{prefix}'")

    # product_weights
    product_weights = {}
    for pid, w in _coerce_weight_map(raw.get("product_weights")).items():
        if pid in valid_products:
            product_weights[pid] = w
        else:
            warnings.append(f"Dropped unknown product id in product_weights: '{pid}'")

    # amount_scale
    amount_scale = {}
    for prefix, w in _coerce_weight_map(raw.get("amount_scale")).items():
        if prefix in valid_prefixes:
            amount_scale[prefix] = w
        else:
            warnings.append(f"Dropped unknown table prefix in amount_scale: '{prefix}'")

    # counterparty_distribution
    counterparty_distribution = {}
    raw_cp = raw.get("counterparty_distribution")
    if isinstance(raw_cp, dict):
        for prefix, dist in raw_cp.items():
            if prefix not in valid_prefixes:
                warnings.append(f"Dropped counterparty_distribution for unknown prefix: '{prefix}'")
                continue
            cleaned = {}
            for cp, w in _coerce_weight_map(dist).items():
                if cp in valid_counterparties:
                    cleaned[cp] = w
                else:
                    warnings.append(f"Dropped unknown counterparty '{cp}' under '{prefix}'")
            if cleaned:
                counterparty_distribution[prefix] = cleaned

    # collateral_distribution
    collateral_distribution = {}
    raw_cc = raw.get("collateral_distribution")
    if isinstance(raw_cc, dict):
        for prefix, dist in raw_cc.items():
            if prefix not in valid_prefixes:
                warnings.append(f"Dropped collateral_distribution for unknown prefix: '{prefix}'")
                continue
            cleaned = {}
            for cc, w in _coerce_weight_map(dist).items():
                if cc in valid_collateral:
                    cleaned[cc] = w
                else:
                    warnings.append(f"Dropped unknown collateral class '{cc}' under '{prefix}'")
            if cleaned:
                collateral_distribution[prefix] = cleaned

    profile = BankProfile(
        bank=bank,
        description=str(raw.get("description", "")),
        table_weights=table_weights,
        product_weights=product_weights,
        amount_scale=amount_scale,
        counterparty_distribution=counterparty_distribution,
        collateral_distribution=collateral_distribution,
    )
    return ProfileValidation(profile=profile, warnings=warnings)


def load_profile(path: str | Path, schema: Schema) -> ProfileValidation:
    """Load and validate a single profile JSON file."""
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"Profile file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Profile is not valid JSON ({path}): {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError(f"Profile root must be a JSON object ({path})")
    return validate_profile(raw, schema)


def profile_path(profiles_dir: str | Path, bank: str) -> Path:
    return Path(profiles_dir) / f"{bank}.json"


def load_bank_profile(profiles_dir: str | Path, bank: str, schema: Schema) -> ProfileValidation:
    """Load the profile for ``bank`` from ``profiles_dir``.

    Raises ProfileError with a clear message when the profile is absent, since
    profiles are required.
    """
    path = profile_path(profiles_dir, bank)
    if not path.is_file():
        raise ProfileError(
            f"No profile found for bank '{bank}' at {path}. "
            f"Generate one with tools/generate_profiles.py or add the file manually."
        )
    return load_profile(path, schema)
