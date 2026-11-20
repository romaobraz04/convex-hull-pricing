"""Unit-commitment model starter functions."""

from __future__ import annotations

from typing import Any
import pandas as pd

import gurobipy as gp
from gurobipy import GRB

from instance import UCinstance


def add_network_flows(model, instance):
    """Add DC flows and return line variables and net imports by balance row."""
    angle = model.addVars(
        instance.nodes["node"].tolist(), instance.periods, lb=-GRB.INFINITY, name="angle"
    )
    for node in instance.nodes.itertuples(index=False):
        if node.is_reference:
            for period in instance.periods:
                angle[node.node, period].LB = 0.0
                angle[node.node, period].UB = 0.0

    flow = {}
    net_imports = [gp.LinExpr() for _ in instance.balance_keys]
    for line in instance.lines.itertuples(index=False):
        for period in instance.periods:
            power = model.addVar(
                lb=-float(line.capacity_mw), ub=float(line.capacity_mw),
                name=f"flow_{line.line}_{period}",
            )
            flow[line.line, period] = power
            model.addConstr(
                power == float(line.susceptance)
                * (angle[line.from_node, period] - angle[line.to_node, period]),
                name=f"dc_{line.line}_{period}",
            )
            net_imports[instance.balance_index[line.from_node, period]] -= power
            net_imports[instance.balance_index[line.to_node, period]] += power
    return flow, net_imports


def build_unit_commitment_model(
    instance: UCinstance, *, include_balance: bool = True
) -> tuple[gp.Model, dict]:
    model = gp.Model("unit_commitment")

    generators = instance.generators
    demand = instance.demand

    G = range(len(generators))
    T = range(len(instance.periods))

    # Variables indexed by (generator, period)
    production = model.addVars(G, T, lb=0, name="production")
    on = model.addVars(G, T, vtype=GRB.BINARY, name="on")
    startup = model.addVars(G, T, vtype=GRB.BINARY, name="startup")

    # Production cost plus start-up cost
    model.setObjective(
        gp.quicksum(
            float(generators.iloc[g]["marginal_cost_eur_per_mwh"]) * production[g, t]
            + float(generators.iloc[g]["startup_cost_eur"]) * startup[g, t]
            for g in G
            for t in T
        ),
        GRB.MINIMIZE,
    )

    for t in T:

        if include_balance and not instance.is_network:
            model.addConstr(
                gp.quicksum(production[g, t] for g in G)
                == float(demand.iloc[t]["demand_mw"]),
                name=f"demand_balance_{t}",
            )

        for g in G:
            row = generators.iloc[g]
            p_min = float(row["p_min_mw"])
            p_max = float(row["p_max_mw"])

            model.addConstr(
                production[g, t] >= p_min * on[g, t],
                name=f"min_output_{g}_{t}",
            )
            model.addConstr(
                production[g, t] <= p_max * on[g, t],
                name=f"max_output_{g}_{t}",
            )

            # Previous status is the initial status in the first period
            previous_on = int(row["initial_on"]) if t == 0 else on[g, t - 1]

            model.addConstr(
                startup[g, t] >= on[g, t] - previous_on,
                name=f"startup_lb_{g}_{t}",
            )
            model.addConstr(
                startup[g, t] <= on[g, t],
                name=f"startup_on_{g}_{t}",
            )
            model.addConstr(
                startup[g, t] <= 1 - previous_on,
                name=f"startup_off_{g}_{t}",
            )

            # ramping constraints
            if instance.instance_name == "ramping":
                shutdown = previous_on - on[g, t] + startup[g, t]
                previous_production = (
                    float(row["initial_output_mw"]) if t == 0 else production[g, t - 1]
                )
                ramp_up = float(row["ramp_up_mw_per_period"])
                ramp_down = float(row["ramp_down_mw_per_period"])
                startup_ramp = row["startup_ramp_mw_per_period"]
                shutdown_ramp = row["shutdown_ramp_mw_per_period"]

                startup_ramp = ramp_up if pd.isna(startup_ramp) else float(startup_ramp)
                shutdown_ramp = (
                    ramp_down if pd.isna(shutdown_ramp) else float(shutdown_ramp)
                )

                model.addConstr(
                    production[g, t] - previous_production
                    <= ramp_up * previous_on + startup_ramp * startup[g, t],
                    name=f"ramp_up_{g}_{t}",
                )
                model.addConstr(
                    previous_production - production[g, t]
                    <= ramp_down * on[g, t] + shutdown_ramp * shutdown,
                    name=f"ramp_down_{g}_{t}",
                )

            # minimum up/down constraints
            if instance.instance_name == "minimum_up_down":
                shutdown = previous_on - on[g, t] + startup[g, t]
                up = min(len(T) - t, int(row["min_up_time_periods"]))
                down = min(len(T) - t, int(row["min_down_time_periods"]))
                model.addConstr(
                    gp.quicksum(on[g, tau] for tau in range(t, t + up))
                    >= up * startup[g, t],
                    name=f"min_up_time_{g}_{t}",
                )
                model.addConstr(
                    gp.quicksum(1 - on[g, tau] for tau in range(t, t + down))
                    >= down * shutdown,
                    name=f"min_down_time_{g}_{t}",
                )

    variables = {
        "production": production,
        "on": on,
        "startup": startup,
    }
    if instance.is_network:
        flow, net_supply = add_network_flows(model, instance)
        for g in G:
            for t in T:
                net_supply[instance.generator_balance_indices[g][t]] += production[g, t]
        if include_balance:
            for i, expression in enumerate(net_supply):
                model.addConstr(
                    expression == float(demand.iloc[i]["demand_mw"]),
                    name=f"demand_balance_{i}",
                )
        variables["flow"] = flow
        variables["net_supply"] = net_supply
    return model, variables


def solve_unit_commitment(instance: UCinstance) -> dict[str, Any]:

    generators = instance.generators
    model, variables = build_unit_commitment_model(instance, include_balance=True)
    model.optimize()

    if model.status == GRB.OPTIMAL:

        dispatch = []

        for g, generator_row in generators.iterrows():
            for t, period in enumerate(instance.periods):
                dispatch.append(
                    {
                        "generator": str(generator_row["generator"]),
                        "period": int(period),
                        "production_mw": float(variables["production"][g, t].X),
                        "on": int(round(variables["on"][g, t].X)),
                        "startup": int(round(variables["startup"][g, t].X)),
                    }
                )

        solution = {
            "status": "optimal",
            "objective_eur": model.objVal,
            "energy_cost_eur": sum(
                float(var.obj) * var.x
                for var in model.getVars()
                if var.varName.startswith("production")
            ),
            "startup_cost_eur": sum(
                float(var.obj) * var.x
                for var in model.getVars()
                if var.varName.startswith("startup")
            ),
            "dispatch": dispatch,
            "runtime_seconds": float(model.Runtime),
        }
        if instance.is_network:
            solution["line_flows"] = [
                {
                    "line": str(line.line),
                    "period": int(period),
                    "from_node": int(line.from_node),
                    "to_node": int(line.to_node),
                    "flow_mw": float(variables["flow"][line.line, period].X),
                }
                for line in instance.lines.itertuples(index=False)
                for period in instance.periods
            ]
        return solution
    else:
        raise RuntimeError(f"Optimization failed with status {model.status}.")
