"""Command-line starter for running one assignment case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from instance import UCinstance
from UCmodel import solve_unit_commitment
from pricing import (
    calculate_lost_opportunity_cost,
    congestion_rent_eur,
    solve_chp_pricing,
    solve_ip_pricing,
)

CODE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = CODE_DIR / "output"
VALID_INSTANCE_NAMES = ("single_period", "minimum_up_down", "ramping", "network")


def run_instance(
    instance_name: str, *, pricing: str = "both", chp_algorithm: str = "subgradient"
) -> dict[str, Any]:
    """Load a case, solve UC, run requested pricing methods, and collect results."""
    if pricing not in ("ip", "chp", "both"):
        raise ValueError(f"Unknown pricing option: {pricing}")

    instance = UCinstance(instance_name)
    uc_solution = solve_unit_commitment(instance)
    results = {"instance": instance_name, "uc": uc_solution}

    if pricing in ("ip", "both"):
        results["ip"] = solve_ip_pricing(instance, uc_solution)

    if pricing in ("chp", "both"):
        chp_solution = solve_chp_pricing(
            instance,
            algorithm=chp_algorithm,
            uc_cost_eur=uc_solution["objective_eur"],
            uc_dispatch=uc_solution["dispatch"],
        )
        if chp_solution is None:
            raise NotImplementedError(f"CHP algorithm {chp_algorithm!r} is unfinished.")
        chp_solution["total_uplift_eur"] = (
            uc_solution["objective_eur"] - chp_solution["dual_objective_eur"]
        )
        chp_solution["settlement_by_generator"] = calculate_lost_opportunity_cost(
            instance, uc_solution["dispatch"], chp_solution["energy_prices"]
        )
        if instance.is_network:
            generator_uplift = sum(
                row["lost_opportunity_cost_eur"]
                for row in chp_solution["settlement_by_generator"]
            )
            chp_solution["generator_uplift_eur"] = generator_uplift
            chp_solution["network_opportunity_cost_eur"] = (
                chp_solution["total_uplift_eur"] - generator_uplift
            )
            chp_solution["congestion_rent_eur"] = congestion_rent_eur(
                uc_solution["line_flows"], chp_solution["energy_prices"]
            )
        results["chp"] = {"algorithm": chp_algorithm, **chp_solution}

    return results


def save_results(results: dict[str, Any], output_path: Path) -> None:
    """Write collected results as JSON in the output folder."""
    content = json.dumps(results, indent=2, allow_nan=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line options and run the selected case."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", choices=VALID_INSTANCE_NAMES, required=True)
    parser.add_argument("--pricing", choices=("ip", "chp", "both"), default="both")
    parser.add_argument(
        "--chp_algorithm",
        choices=("subgradient", "cutting_plane", "dw"),
        default="subgradient",
    )
    args = parser.parse_args(argv)

    results = run_instance(
        args.instance, pricing=args.pricing, chp_algorithm=args.chp_algorithm
    )
    save_results(results, OUTPUT_DIR / f"{args.instance}_results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
