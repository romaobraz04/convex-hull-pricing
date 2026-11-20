# Results and figures

The saved comparison runs are `<instance>_subgradient_results.json`,
`<instance>_level_results.json`, and `<instance>_dw_results.json`. The regular
runner writes `<instance>_results.json` and replaces that file on each run.
Some bundled unsuffixed files come from earlier versions of the runner, so use
the suffixed snapshots for a consistent comparison.

## JSON fields

| Section | Contents |
| --- | --- |
| `uc` | Total objective, generation and start-up costs, and dispatch with `production_mw`, `on`, and `startup` for each generator and period |
| `ip` | Energy prices, commitment duals and payments, and signed cost-recovery residuals |
| `chp` | Energy prices, best evaluated dual objective, uplift, and lost opportunity cost by generator |
| CHP diagnostics | `dual_history_eur` records the running best dual value. `gap_eur`, where present, is the difference between the upper bound and the best evaluated value. Timing fields distinguish solver time from elapsed time. |

Energy prices are in EUR/MWh and financial totals are in EUR. Network runs
include UC line flows, nodal energy prices, and congestion rent under each
pricing method. The `chp` section reports generator uplift and network
opportunity cost separately from total uplift.

## Generate report figures

The plotting script reads the three non-network cases and writes PDFs to
`../overleaf/report_assets/figures/`, relative to the repository root. It
expects IP and subgradient CHP results in each unsuffixed JSON. Run these
commands from the root to refresh those files and generate the figures.

```sh
python -m pip install matplotlib
python run.py --instance single_period --pricing both --chp_algorithm subgradient
python run.py --instance minimum_up_down --pricing both --chp_algorithm subgradient
python run.py --instance ramping --pricing both --chp_algorithm subgradient
python plot_report.py
```

The PDFs include UC dispatch, IP and CHP prices, and a convergence comparison
across the three pricing algorithms.
