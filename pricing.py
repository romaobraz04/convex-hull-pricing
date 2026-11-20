"""IP and convex-hull pricing starter functions."""

from __future__ import annotations

from copy import deepcopy
from math import sqrt
from time import perf_counter
from typing import Any

import gurobipy as gp
from gurobipy import GRB

from instance import UCinstance
import UCmodel


def _price_records(instance, values):
    return [
        {
            "period": int(period),
            **({"node": int(node)} if instance.is_network else {}),
            "price_eur_per_mwh": float(value),
        }
        for (node, period), value in zip(instance.balance_keys, values)
    ]


def _price_lookup(prices):
    return {
        (row.get("node"), row["period"]): row["price_eur_per_mwh"] for row in prices
    }


def congestion_rent_eur(line_flows, prices):
    """Value the scheduled flows at the difference in nodal energy prices."""
    price_by_key = _price_lookup(prices)
    return sum(
        row["flow_mw"]
        * (
            price_by_key[row["to_node"], row["period"]]
            - price_by_key[row["from_node"], row["period"]]
        )
        for row in line_flows
    )


def solve_ip_pricing(
    instance: UCinstance, uc_solution: dict[str, Any]
) -> dict[str, Any]:

    generators = instance.generators

    # build the unit commitment model
    ip_model, variables = UCmodel.build_unit_commitment_model(instance)

    # LP relaxation, set the binary variables to continuous
    for var in variables["on"].values():
        var.VType = GRB.CONTINUOUS
        var.LB = -GRB.INFINITY
        var.UB = GRB.INFINITY

    for var in variables["startup"].values():
        var.VType = GRB.CONTINUOUS
        var.LB = -GRB.INFINITY
        var.UB = GRB.INFINITY

    # add explicit fixing constraints using the UC solution values
    generator_index = {row["generator"]: g for g, row in generators.iterrows()}
    period_index = {period: t for t, period in enumerate(instance.periods)}

    fix_on = {}
    fix_startup = {}

    for record in uc_solution["dispatch"]:
        g = generator_index[record["generator"]]
        t = period_index[record["period"]]

        fix_on[g, t] = ip_model.addConstr(
            variables["on"][g, t] == record["on"],
            name=f"fix_on_{g}_{t}",
        )
        fix_startup[g, t] = ip_model.addConstr(
            variables["startup"][g, t] == record["startup"],
            name=f"fix_startup_{g}_{t}",
        )

    # Optimize the IP pricing model
    ip_model.optimize()

    if ip_model.Status == GRB.OPTIMAL:
        prices = _price_records(
            instance,
            (ip_model.getConstrByName(f"demand_balance_{i}").Pi
             for i in range(len(instance.balance_keys))),
        )

        settlement = calculate_commitment_payment_cost_recovery(
            instance, uc_solution["dispatch"], prices, fix_on, fix_startup
        )
        if instance.is_network:
            settlement["congestion_rent_eur"] = congestion_rent_eur(
                uc_solution["line_flows"], prices
            )
        return {
            "status": "optimal",
            "objective_eur": float(ip_model.ObjVal),
            "energy_prices": prices,
            "runtime_seconds": float(ip_model.Runtime),
            **settlement,
        }
    else:
        raise RuntimeError(f"IP pricing failed with status {ip_model.Status}.")


def solve_chp_pricing(
    instance: UCinstance,
    algorithm: str = "subgradient",
    *,
    uc_cost_eur: float | None = None,
    uc_dispatch: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if algorithm == "subgradient":
        return _solve_chp_subgradient(instance)
    if algorithm == "cutting_plane":
        return _solve_chp_level(instance, uc_cost_eur=uc_cost_eur)
    if algorithm == "dw":
        return _solve_chp_dw(instance, uc_dispatch=uc_dispatch)
    raise ValueError(f"Unknown CHP algorithm: {algorithm}")


def _schedule_revenues_and_costs(instance, dispatch, prices):
    """Value a schedule at the applicable energy prices."""
    generator_data = instance.generators.set_index("generator").to_dict("index")
    price_by_key = _price_lookup(prices)
    totals = {
        generator: {"energy_revenue_eur": 0.0, "operating_cost_eur": 0.0}
        for generator in generator_data
    }

    for row in dispatch:
        generator = row["generator"]
        output = row["production_mw"]
        data = generator_data[generator]
        totals[generator]["energy_revenue_eur"] += (
            price_by_key[data.get("node"), row["period"]] * output
        )
        totals[generator]["operating_cost_eur"] += (
            float(data["marginal_cost_eur_per_mwh"]) * output
            + float(data["startup_cost_eur"]) * row["startup"]
        )
    return totals


def calculate_commitment_payment_cost_recovery(
    instance, dispatch, prices, fix_on, fix_startup
) -> dict[str, Any]:
    """Settle the UC schedule using the energy and binary fixing duals."""
    totals = _schedule_revenues_and_costs(instance, dispatch, prices)
    generator_index = dict(zip(instance.generators["generator"], range(len(totals))))
    periods = instance.periods
    period_index = {period: t for t, period in enumerate(periods)}
    commitment_duals = []
    for generator in totals:
        totals[generator]["commitment_payment_eur"] = 0.0

    for row in dispatch:
        generator = row["generator"]
        period = row["period"]
        g, t = generator_index[generator], period_index[period]
        on_dual = float(fix_on[g, t].Pi)
        startup_dual = float(fix_startup[g, t].Pi)
        payment = on_dual * row["on"] + startup_dual * row["startup"]
        totals[generator]["commitment_payment_eur"] += payment
        commitment_duals.append({
            "generator": generator,
            "period": period,
            "on_dual_eur": on_dual,
            "startup_dual_eur": startup_dual,
            "commitment_payment_eur": payment,
        })

    by_generator = []
    for generator, amounts in totals.items():
        residual = (
            amounts["operating_cost_eur"]
            - amounts["energy_revenue_eur"]
            - amounts["commitment_payment_eur"]
        )
        by_generator.append({
            "generator": generator,
            **amounts,
            "signed_cost_recovery_residual_eur": residual,
        })

    return {
        "commitment_duals": commitment_duals,
        "settlement_by_generator": by_generator,
        "total_commitment_payment_eur": sum(
            row["commitment_payment_eur"] for row in by_generator
        ),
        "total_signed_cost_recovery_residual_eur": sum(
            row["signed_cost_recovery_residual_eur"] for row in by_generator
        ),
    }


def calculate_lost_opportunity_cost(instance, dispatch, prices) -> list[dict[str, Any]]:
    """Compare each unit's best response with its profit on the UC schedule."""
    scheduled = _schedule_revenues_and_costs(instance, dispatch, prices)
    periods = instance.periods
    generators = instance.generators["generator"].tolist()

    # The response model has no balance constraint, so all generators
    # independently maximise profit in this one solve.
    model, variables, _ = _solve_chp_response(instance, prices)
    with model:
        best_dispatch = [
            {
                "generator": generators[g],
                "period": periods[t],
                "production_mw": float(power.X),
                "startup": int(round(variables["startup"][g, t].X)),
            }
            for (g, t), power in variables["production"].items()
        ]
    best = _schedule_revenues_and_costs(instance, best_dispatch, prices)

    by_generator = []
    for generator, amounts in scheduled.items():
        scheduled_profit = amounts["energy_revenue_eur"] - amounts["operating_cost_eur"]
        best_profit = (
            best[generator]["energy_revenue_eur"] - best[generator]["operating_cost_eur"]
        )
        by_generator.append({
            "generator": generator,
            **amounts,
            "scheduled_profit_eur": scheduled_profit,
            "best_profit_eur": best_profit,
            "lost_opportunity_cost_eur": best_profit - scheduled_profit,
        })
    return by_generator


def _solve_chp_subgradient(
    instance: UCinstance, max_iterations: int = 1000
) -> dict[str, Any]:

    prices = _price_records(instance, [0.0] * len(instance.balance_keys))

    best_dual_value = float("-inf")
    best_prices = []
    solver_runtime_seconds = 0.0
    dual_history_eur = []

    start_time = perf_counter()
    for k in range(max_iterations):
        dual_value, mismatch, solve_time = _evaluate_chp_dual(instance, prices)
        solver_runtime_seconds += solve_time

        if dual_value > best_dual_value:
            best_dual_value = dual_value
            best_prices = deepcopy(prices)
        dual_history_eur.append(best_dual_value)

        step_size = 0.1 / sqrt(k + 1)
        for t in range(len(prices)):
            prices[t]["price_eur_per_mwh"] += step_size * mismatch[t]

    return {
        "energy_prices": best_prices,
        "dual_objective_eur": best_dual_value,
        "iterations": max_iterations,
        "dual_history_eur": dual_history_eur,
        "solver_runtime_seconds": solver_runtime_seconds,
        "runtime_seconds": perf_counter() - start_time,
    }


def _solve_chp_level(
    instance: UCinstance,
    max_iterations: int = 1000,
    tol_eur: float = 0.01,
    *,
    uc_cost_eur: float | None = None,
) -> dict[str, Any]:
    """Maximise the CHP dual with cutting planes and midpoint projection."""

    if uc_cost_eur is None:
        uc_cost_eur = float(UCmodel.solve_unit_commitment(instance)["objective_eur"])

    prices = _price_records(instance, [0.0] * len(instance.balance_keys))

    master = gp.Model("master_LP")
    start_time = perf_counter()
    price_vars = master.addVars(len(prices), name="prices", lb=-GRB.INFINITY)
    theta = master.addVar(name="theta", lb=-GRB.INFINITY, ub=uc_cost_eur)
    master.setObjective(theta, GRB.MAXIMIZE)

    best_dual_value = float("-inf")
    best_prices = []
    solver_runtime_seconds = 0.0
    dual_history_eur = []
    for k in range(1, max_iterations + 1):
        dual_value, mismatch, solve_time = _evaluate_chp_dual(instance, prices)
        solver_runtime_seconds += solve_time
        if dual_value > best_dual_value:
            best_dual_value = dual_value
            best_prices = deepcopy(prices)
        dual_history_eur.append(best_dual_value)

        master.addConstr(
            theta
            <= dual_value
            + gp.quicksum(
                mismatch[t] * (price_vars[t] - prices[t]["price_eur_per_mwh"])
                for t in range(len(prices))
            ),
            name=f"cut_{k}",
        )
        master.optimize()
        if master.Status != GRB.OPTIMAL:
            raise RuntimeError(f"Master problem failed with status {master.Status}")
        solver_runtime_seconds += float(master.Runtime)

        upper_bound = float(master.ObjVal)
        gap_eur = max(0.0, upper_bound - best_dual_value)
        if gap_eur <= tol_eur or k == max_iterations:
            break

        # reuse cuts for the projection QP. Enforcing theta >= level requires every cut to be at least that high at the projected prices
        theta.LB = best_dual_value + 0.5 * gap_eur
        master.setObjective(
            gp.quicksum(
                (price_vars[t] - prices[t]["price_eur_per_mwh"]) ** 2
                for t in range(len(prices))
            ),
            GRB.MINIMIZE,
        )
        master.optimize()
        if master.Status != GRB.OPTIMAL:
            raise RuntimeError(f"Level projection failed with status {master.Status}")
        solver_runtime_seconds += float(master.Runtime)

        for t in range(len(prices)):
            prices[t]["price_eur_per_mwh"] = float(price_vars[t].X)

        theta.LB = -GRB.INFINITY
        master.setObjective(theta, GRB.MAXIMIZE)

    return {
        "energy_prices": best_prices,
        "dual_objective_eur": best_dual_value,
        "upper_bound_eur": upper_bound,
        "gap_eur": gap_eur,
        "status": "converged" if gap_eur <= tol_eur else "iteration_limit",
        "iterations": k,
        "dual_history_eur": dual_history_eur,
        "solver_runtime_seconds": solver_runtime_seconds,
        "runtime_seconds": perf_counter() - start_time,
    }


def _solve_chp_dw(
    instance: UCinstance,
    max_iterations: int = 1000,
    tol_eur: float = 0.01,
    *,
    uc_dispatch: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Solve the convexified dispatch LP by generating unit schedule columns."""
    if max_iterations < 1 or tol_eur <= 0:
        raise ValueError("Dantzig-Wolfe requires a positive iteration limit and tolerance.")
    if uc_dispatch is None:
        uc_dispatch = UCmodel.solve_unit_commitment(instance)["dispatch"]

    start_time = perf_counter()
    periods = instance.periods
    demand = instance.demand["demand_mw"].tolist()
    generators = instance.generators["generator"].tolist()
    marginal_costs = instance.generators["marginal_cost_eur_per_mwh"].tolist()
    startup_costs = instance.generators["startup_cost_eur"].tolist()
    dispatch = {(row["generator"], row["period"]): row for row in uc_dispatch}

    solver_runtime_seconds = 0.0
    columns = 0
    dual_history_eur = []
    best_dual_value = float("-inf")
    best_prices = []

    with gp.Model("dw_master") as master:
        if instance.is_network:
            _, net_imports = UCmodel.add_network_flows(master, instance)
        else:
            net_imports = [gp.LinExpr() for _ in demand]
        balance = [
            master.addConstr(net_imports[i] == load, name=f"balance_{i}")
            for i, load in enumerate(demand)
        ]
        unit_balance = [
            [balance[i] for i in indices]
            for indices in instance.generator_balance_indices
        ]
        convexity = [
            master.addConstr(gp.LinExpr() == 1.0, name=f"convexity_{g}")
            for g in range(len(generators))
        ]
        master.update()

        # One schedule per unit from the UC solution makes the first LP feasible.
        for g, generator in enumerate(generators):
            rows = [dispatch[generator, period] for period in periods]
            output = [row["production_mw"] for row in rows]
            cost = marginal_costs[g] * sum(output) + startup_costs[g] * sum(
                row["startup"] for row in rows
            )
            column = gp.Column(output + [1.0], unit_balance[g] + [convexity[g]])
            master.addVar(obj=cost, column=column, name=f"schedule_{g}_initial")
            columns += 1

        for k in range(1, max_iterations + 1):
            master.optimize()
            if master.Status != GRB.OPTIMAL:
                raise RuntimeError(f"Dantzig-Wolfe master failed with status {master.Status}")
            solver_runtime_seconds += float(master.Runtime)
            upper_bound = float(master.ObjVal)
            prices = _price_records(instance, (constraint.Pi for constraint in balance))

            # The shared response solve is separable and finds every unit's
            # minimum cost minus energy revenue at the master prices.
            response, variables, price_by_t = _solve_chp_response(instance, prices)
            candidates = []
            with response:
                solver_runtime_seconds += float(response.Runtime)
                dual_value = float(response.ObjVal) + sum(
                    price * load for price, load in zip(price_by_t, demand)
                )
                for g in range(len(generators)):
                    output = [
                        float(variables["production"][g, t].X)
                        for t in range(len(periods))
                    ]
                    startups = sum(
                        round(variables["startup"][g, t].X)
                        for t in range(len(periods))
                    )
                    cost = marginal_costs[g] * sum(output) + startup_costs[g] * startups
                    revenue = sum(
                        price_by_t[i] * power
                        for i, power in zip(instance.generator_balance_indices[g], output)
                    )
                    reduced_cost = cost - revenue - convexity[g].Pi
                    if reduced_cost < -1e-8:
                        candidates.append((g, output, cost))

            if dual_value > best_dual_value:
                best_dual_value = dual_value
                best_prices = prices
            dual_history_eur.append(best_dual_value)
            gap_eur = max(0.0, upper_bound - best_dual_value)
            if gap_eur <= tol_eur or k == max_iterations:
                break
            if not candidates:
                raise RuntimeError("Dantzig-Wolfe stalled before its gap reached tolerance.")

            for g, output, cost in candidates:
                column = gp.Column(output + [1.0], unit_balance[g] + [convexity[g]])
                master.addVar(obj=cost, column=column, name=f"schedule_{g}_{k}")
                columns += 1

    return {
        "energy_prices": best_prices,
        "dual_objective_eur": best_dual_value,
        "upper_bound_eur": upper_bound,
        "gap_eur": gap_eur,
        "status": "converged" if gap_eur <= tol_eur else "iteration_limit",
        "iterations": k,
        "columns": columns,
        "dual_history_eur": dual_history_eur,
        "solver_runtime_seconds": solver_runtime_seconds,
        "runtime_seconds": perf_counter() - start_time,
    }


def _evaluate_chp_dual(
    instance: UCinstance, prices: list[dict[str, Any]]
) -> tuple[float, list[float], float]:
    """Return the dual value, demand mismatch, and Gurobi solve time."""

    uc_model, variables, price_by_t = _solve_chp_response(instance, prices)
    demand_mw = instance.demand["demand_mw"].tolist()
    total_output = [0.0] * len(demand_mw)

    with uc_model:
        if instance.is_network:
            total_output = [expression.getValue() for expression in variables["net_supply"]]
        else:
            for (_, t), power in variables["production"].items():
                total_output[t] += power.X

        demand_value = sum(
            price_by_t[t] * demand for t, demand in enumerate(demand_mw)
        )
        dual_value = demand_value + uc_model.ObjVal
        solve_time = float(uc_model.Runtime)

    mismatch = [demand - output for demand, output in zip(demand_mw, total_output)]
    return dual_value, mismatch, solve_time


def _solve_chp_response(instance, prices):
    """Solve the generator and, when applicable, network responses."""
    price_lookup = _price_lookup(prices)
    price_by_t = [price_lookup[key] for key in instance.balance_keys]
    uc_model, variables = UCmodel.build_unit_commitment_model(
        instance, include_balance=False
    )
    # The evaluated objective serves as a lower bound in the level method.
    uc_model.Params.MIPGap = 0.0
    uc_model.Params.MIPGapAbs = 0.0
    uc_model.update()
    original_cost = uc_model.getObjective()

    if instance.is_network:
        revenue = gp.quicksum(
            price * supply for price, supply in zip(price_by_t, variables["net_supply"])
        )
    else:
        revenue = gp.quicksum(
            price_by_t[t] * power
            for (g, t), power in variables["production"].items()
        )
    uc_model.setObjective(original_cost - revenue, GRB.MINIMIZE)
    uc_model.optimize()

    if uc_model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"CHP evaluation failed: status {uc_model.Status}")

    return uc_model, variables, price_by_t
