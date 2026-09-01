#!/usr/bin/env python3
"""Generate bank profiles for the FR 2052a mock data generator via OpenRouter.

STANDALONE tool. Not imported by the application runtime. It calls an LLM once
per bank to produce a realistic funding-shape profile, validates the result
against the FR 2052a schema (dropping any hallucinated references), and writes
bank_profiles/<Bank>.json.

Setup:
    cp .env.example .env    # then edit .env to add OPENROUTER_API_KEY
    python -m pip install requests

Usage:
    python tools/generate_profiles.py --banks Wells,BoFA,USWest,Chase,CapOne
    python tools/generate_profiles.py --banks Wells --out bank_profiles

The .env file (gitignored) supplies OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
and OPENROUTER_MODEL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when run as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fr2052a_mockgen.config import ConfigError, load_openrouter_config  # noqa: E402
from fr2052a_mockgen.profiles import validate_profile  # noqa: E402
from fr2052a_mockgen.schema_loader import load_schema  # noqa: E402

DEFAULT_SCHEMA = "schema/fr2052a_schema.json"
DEFAULT_OUT = "bank_profiles"


def _schema_summary(schema) -> str:
    """Compact description of tables + valid values for the prompt."""
    lines = ["FR 2052a tables (prefix: subtable):"]
    for t in schema.tables:
        pids = ", ".join(p.id for p in t.products)
        lines.append(f"- {t.prefix} ({t.name}/{t.subtable}): {pids}")
    lines.append("")
    lines.append("Counterparty values: " + ", ".join(schema.enum_values("Counterparty")))
    lines.append("CollateralClass values: " + ", ".join(schema.enum_values("CollateralClass")))
    return "\n".join(lines)


def build_prompt(bank: str, schema) -> str:
    return f"""You are an expert in U.S. bank liquidity reporting (Federal Reserve FR 2052a).
Produce a realistic *funding-shape profile* for the institution "{bank}" as JSON only.

The profile biases a mock-data generator toward how this bank's balance sheet
actually looks. Use these table prefixes and allowed values EXACTLY as given;
do not invent product IDs, counterparties, or collateral classes.

{_schema_summary(schema)}

Return ONLY a JSON object with this shape (all sections optional, floats > 0):
{{
  "bank": "{bank}",
  "description": "one sentence on this bank's funding profile",
  "table_weights": {{ "<prefix>": <relative row-count weight> }},
  "product_weights": {{ "<product_id>": <relative row-count weight> }},
  "amount_scale": {{ "<prefix>": <multiplier on typical amounts> }},
  "counterparty_distribution": {{ "<prefix>": {{ "<Counterparty>": <weight> }} }},
  "collateral_distribution": {{ "<prefix>": {{ "<CollateralClass>": <weight> }} }}
}}

Guidance: a large retail bank should weight O.D (deposits) heavily with Retail /
Small Business counterparties; a capital-markets-heavy bank should weight I.S /
O.S (secured financing) and S.DC (derivatives) with Bank / Broker-Dealer
counterparties and HQLA Level 1 collateral (A-1-Q, G-2-Q). Scale amounts to the
bank's size. Output JSON only, no prose, no code fences."""


def call_openrouter(cfg, prompt: str, timeout: int = 90, max_tokens: int = 4000) -> str:
    try:
        import requests
    except ImportError:
        sys.exit("requests is required. Install it with: pip install requests")

    try:
        # (connect timeout, read timeout). The read timeout applies per network
        # read; a bounded max_tokens keeps the total response small so a slow
        # model still returns within a predictable window.
        resp = requests.post(
            f"{cfg.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://localhost/fr2052a-mockgen",
                "X-Title": "FR2052a Mock Data Generator",
            },
            json={
                "model": cfg.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.4,
                "max_tokens": max_tokens,
                "stream": False,
                "response_format": {"type": "json_object"},
            },
            timeout=(10, timeout),
        )
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            f"OpenRouter request timed out (connect 10s, read {timeout}s). "
            f"The model may be slow; try --timeout <seconds> or a faster model."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"OpenRouter request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise RuntimeError(
            f"OpenRouter returned HTTP {resp.status_code}: {resp.text[:300]}"
        )
    data = resp.json()
    try:
        choice = data["choices"][0]
        message = choice.get("message", {})
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenRouter response shape: {data}") from exc

    # Some models return content in message.content; others (reasoning models or
    # certain routed models) may leave content null and put text elsewhere.
    content = message.get("content")
    if not content:
        content = message.get("reasoning") or message.get("refusal")
    if not content:
        finish = choice.get("finish_reason", "unknown")
        raise RuntimeError(
            f"Model returned empty content (finish_reason='{finish}'). "
            f"This model may not follow the JSON instruction; try a different "
            f"OPENROUTER_MODEL (e.g. anthropic/claude-3.5-sonnet or openai/gpt-4o)."
        )
    return content


def _extract_json(text: str) -> dict:
    """Extract a JSON object from model output, tolerating code fences/prose."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Model response was empty")
    text = text.strip()
    if text.startswith("```"):
        # strip ``` or ```json fences
        text = text.split("```", 2)[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model response")
    return json.loads(text[start : end + 1])


def generate_one(bank: str, schema, cfg, out_dir: Path, timeout: int = 90) -> Path:
    prompt = build_prompt(bank, schema)
    content = call_openrouter(cfg, prompt, timeout=timeout)
    raw = _extract_json(content)
    raw.setdefault("bank", bank)
    result = validate_profile(raw, schema)
    for w in result.warnings:
        print(f"  [warn] {bank}: {w}", file=sys.stderr)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{bank}.json"
    payload = {
        "bank": result.profile.bank,
        "description": result.profile.description,
        "table_weights": result.profile.table_weights,
        "product_weights": result.profile.product_weights,
        "amount_scale": result.profile.amount_scale,
        "counterparty_distribution": result.profile.counterparty_distribution,
        "collateral_distribution": result.profile.collateral_distribution,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate FR 2052a bank profiles via OpenRouter.")
    parser.add_argument("--banks", required=True,
                        help="Comma-separated bank names, e.g. Wells,BoFA,Chase")
    parser.add_argument("--schema", type=Path, default=Path(DEFAULT_SCHEMA))
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--timeout", type=int, default=90,
                        help="Per-request read timeout in seconds (default: 90)")
    args = parser.parse_args(argv)

    banks = [b.strip() for b in args.banks.split(",") if b.strip()]
    if not banks:
        parser.error("--banks must contain at least one name")

    try:
        cfg = load_openrouter_config(args.env)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    schema = load_schema(args.schema)
    print(f"Using model '{cfg.model}' at {cfg.base_url} to generate "
          f"{len(banks)} profile(s).", flush=True)
    for i, bank in enumerate(banks, start=1):
        print(f"  [{i}/{len(banks)}] requesting profile for {bank} ...", flush=True)
        try:
            path = generate_one(bank, schema, cfg, args.out, timeout=args.timeout)
            print(f"      wrote {path}", flush=True)
        except Exception as exc:  # noqa: BLE001 - surface any API/parse failure clearly
            print(f"      [error] {bank}: {exc}", file=sys.stderr, flush=True)
            return 1
    print("Done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
