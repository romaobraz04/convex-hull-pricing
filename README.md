# Convex Hull Pricing

Compare electricity prices and generator settlements for the same unit-commitment dispatch. The examples show how start-up costs, minimum up and down times, ramp limits, and transmission congestion affect energy prices and uplift.

## What the model computes

1. **Unit commitment (UC).** Solve a mixed-integer model that meets demand at minimum generation and start-up cost. It schedules each generator's on/off status, start-ups, and output.
2. **Integer programming (IP) pricing.** Fix the commitment and start-up decisions from the UC solution, then solve a linear program. The demand-balance duals give energy prices. The duals of the fixing constraints determine commitment payments.
3. **Convex hull pricing (CHP).** Relax the demand-balance constraints and find energy prices by maximizing the resulting Lagrangian dual. Each generator's lost opportunity cost is the difference between its best feasible profit at those prices and its profit on the scheduled dispatch. The runner reports total CHP uplift as the UC cost minus the best evaluated dual objective.

## Quick start

From the repository root, install the solver and data dependencies. The examples were tested with Python 3.12 and Gurobi 13.0.1. The pip distribution of `gurobipy` includes a size-limited license. [Gurobi installation and licensing](https://support.gurobi.com/hc/en-us/articles/360044290292-How-do-I-install-Gurobi-for-Python)


```sh
python -m pip install -r requirements.txt
python run.py --instance single_period --pricing both --chp_algorithm dw
```

The command writes `output/single_period_results.json`. Each run overwrites `output/<instance>_results.json` for the selected case, regardless of method. The [saved comparison runs](output/) use separate suffixes and are available to inspect without installing the solver.

## Case studies

| `--instance` | Generators | Hourly periods | What the case adds |
| --- | ---: | ---: | --- |
| [`single_period`](data/single_period/) | 3 | 1 | Start-up costs and generator output limits in a single hour |
| [`minimum_up_down`](data/minimum_up_down/) | 3 | 5 | Minimum on and off durations across hours |
| [`ramping`](data/ramping/) | 3 | 4 | Output changes between hours and limits during start-up and shut-down |
| [`network`](data/network/) | 3 | 1 | A two-node DC network with a 30 MW line and nodal prices |

See the [data dictionary](data/README.md) for CSV columns, units, and case assumptions.

## Run and compare methods

Use `--pricing ip` or `--pricing chp` for a single pricing method. The default, `both`, reports both methods. The runner always solves unit commitment first.

| `--chp_algorithm` | How it computes prices |
| --- | --- |
| `subgradient` | Updates prices using the mismatch between demand and supply and retains the best dual value over 1,000 iterations. This is the default. |
| `cutting_plane` | Uses a cutting-plane master and a level projection. Saved comparison files label this method `level`. |
| `dw` | Uses Dantzig–Wolfe column generation to add feasible schedules to a restricted master and obtains energy prices from its balance duals. |

The level method and Dantzig–Wolfe report an upper bound and stop when the gap is within €0.01 or the iteration limit is reached. Inspect `status` and `gap_eur` when comparing runs.

```sh
python run.py --instance minimum_up_down --pricing ip
python run.py --instance ramping --pricing both --chp_algorithm subgradient
python run.py --instance network --pricing both --chp_algorithm cutting_plane
```

## Example results

These values come from the saved Dantzig–Wolfe comparison runs. CHP uplift is the difference between the two cost columns.

| Case | UC cost (€) | CHP dual objective (€) | CHP uplift (€) |
| --- | ---: | ---: | ---: |
| [Single period](output/single_period_dw_results.json) | 1,200 | 1,050 | 150 |
| [Minimum up and down](output/minimum_up_down_dw_results.json) | 9,790 | 8,286 | 1,504 |
| [Ramping](output/ramping_dw_results.json) | 8,200 | 8,200 | 0 |
| [Two-node network](output/network_dw_results.json) | 1,500 | 1,250 | 250 |

In the single-period example, the energy price is €10/MWh under IP pricing and €15/MWh under CHP. In the network example, the CHP prices are €15/MWh at node 1 and €25/MWh at node 2. See the [output guide](output/README.md) for the JSON fields and the plotting workflow.

## Repository layout

| Path | Purpose |
| --- | --- |
| [`run.py`](run.py) | Command-line entry point and JSON export |
| [`instance.py`](instance.py) | CSV input and indexing by period and network node |
| [`UCmodel.py`](UCmodel.py) | Unit-commitment model and DC line flows |
| [`pricing.py`](pricing.py) | IP pricing, all three CHP algorithms, and settlement calculations |
| [`plot_report.py`](plot_report.py) | PDF price, dispatch, and convergence plots from saved JSON |
| [`data/`](data/) and [`output/`](output/) | Case inputs, reference dispatches, and saved results |

## Coursework and references

Developed for *Optimisation in Energy Systems* (FEM21063) at Erasmus University Rotterdam, assignment *Pricing with Binary Decisions*. Coursework by Romão Noronha Braz and Lachezar Stoychev.

- Stevens and Papavasiliou (2022). [Application of the Level Method for Computing Locational Convex Hull Prices](https://doi.org/10.1109/TPWRS.2022.3142567).
- Andrianesis, Bertsimas, Caramanis, and Hogan (2022). [Computation of Convex Hull Prices in Electricity Markets with Non-Convexities Using Dantzig–Wolfe Decomposition](https://doi.org/10.1109/TPWRS.2021.3122000).
