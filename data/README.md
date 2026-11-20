# Instance data

Each case has a folder directly under `data/`. All four folders contain:

- `generators.csv` has one row per generator.
- `demand.csv` records demand by period, and by node in the network case.
- `reference_dispatch.csv` records the comparison dispatch supplied with the coursework. The solver computes its own dispatch from the model constraints.

## `generators.csv` columns

| Column | Meaning |
| --- | --- |
| `generator` | Generator name |
| `p_min_mw`, `p_max_mw` | Minimum and maximum output while committed |
| `marginal_cost_eur_per_mwh` | Variable production cost |
| `startup_cost_eur` | Cost for an off-to-on transition |
| `min_up_time_periods`, `min_down_time_periods` | Minimum on/off duration after a transition |
| `ramp_up_mw_per_period`, `ramp_down_mw_per_period` | Normal ramp limits |
| `startup_ramp_mw_per_period`, `shutdown_ramp_mw_per_period` | Special start-up/shut-down ramp limits |
| `initial_on` | Initial commitment (0 or 1) |
| `initial_output_mw` | Output immediately before period 1 |

Empty cells indicate unspecified or inapplicable parameters. The ramping case
uses 0 MW minimum output. Its shut-down ramp limits for B and C are 80 MW and
60 MW per period, respectively. The model uses the normal ramp limit when a
start-up or shut-down ramp limit is blank.

## Network case

The `network/` folder also has `nodes.csv` (`node,is_reference`) and `lines.csv`
(`line,from_node,to_node,susceptance,capacity_mw`). Its `generators.csv` adds a
`node` column, and its `demand.csv` uses `node,period,demand_mw`.
The two-node case uses node 1 as the angle reference and a 30 MW line.

## Other files

Outside the network case, `demand.csv` has columns `period,demand_mw`, with
periods numbered from 1.
`reference_dispatch.csv` has columns `generator,period,generation_mw`.

All periods are one hour, so average power in MW and energy in MWh have the
same numeric value within a period.
