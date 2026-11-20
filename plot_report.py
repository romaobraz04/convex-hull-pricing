"""Build report figures from saved JSON results without running a solver."""

import json
from pathlib import Path

import matplotlib.pyplot as plt

CODE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = CODE_DIR / "output"
FIGURE_DIR = CODE_DIR.parent / "overleaf" / "report_assets" / "figures"
CASES = (
    ("single_period", "Single period"),
    ("minimum_up_down", "Minimum up/down"),
    ("ramping", "Ramping"),
)
GENERATOR_COLORS = ("#276b83", "#d48735", "#638858")
CONVERGENCE_METHODS = (
    ("subgradient", "Subgradient", "#ab4f21", "-"),
    ("level", "Level", "#276b83", "--"),
    ("dw", "Dantzig–Wolfe", "#638858", "-."),
)


def load_results(suffix="", algorithm="subgradient"):
    results = []
    for name, title in CASES:
        path = OUTPUT_DIR / f"{name}{suffix}_results.json"
        with path.open(encoding="utf-8-sig") as file:
            result = json.load(file)
        if result.get("chp", {}).get("algorithm") != algorithm:
            raise ValueError(f"{path.name} must contain the saved {algorithm} run.")
        results.append((title, result))
    return results


def plot_prices(cases, chp_label="Subgradient CHP", filename="energy_prices.pdf"):
    fig, axes = plt.subplots(
        1, len(cases), figsize=(7.0, 2.3), sharey=True, layout="constrained"
    )
    for ax, (title, result) in zip(axes, cases):
        for key, label, color, marker, linestyle in (
            ("ip", "IP", "#276b83", "o", "-"),
            ("chp", chp_label, "#ab4f21", "s", "--"),
        ):
            prices = sorted(result[key]["energy_prices"], key=lambda row: row["period"])
            periods = [row["period"] for row in prices]
            values = [row["price_eur_per_mwh"] for row in prices]
            ax.plot(periods, values, label=label, color=color, marker=marker,
                    linestyle=linestyle, markersize=4, linewidth=1.4)
        ax.axhline(0, color="#767676", linewidth=0.7)
        ax.set(title=title, xlabel="Period", xticks=periods,
               xlim=(periods[0] - 0.38, periods[-1] + 0.38))
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Energy price (€/MWh)")
    axes[0].legend(loc="lower left", frameon=False, fontsize=8)
    fig.savefig(FIGURE_DIR / filename)
    plt.close(fig)


def plot_dispatch(cases):
    fig, axes = plt.subplots(
        1, len(cases), figsize=(7.0, 2.3), sharey=True, layout="constrained"
    )
    for ax, (title, result) in zip(axes, cases):
        dispatch = result["uc"]["dispatch"]
        periods = sorted({row["period"] for row in dispatch})
        generators = sorted({row["generator"] for row in dispatch})
        production = {
            (row["generator"], row["period"]): row["production_mw"] for row in dispatch
        }
        bottom = [0.0] * len(periods)
        for index, generator in enumerate(generators):
            values = [production[generator, t] for t in periods]
            ax.bar(periods, values, bottom=bottom, width=0.60, label=generator,
                   color=GENERATOR_COLORS[index])
            bottom = [base + value for base, value in zip(bottom, values)]
        ax.set(title=title, xlabel="Period", xticks=periods,
               xlim=(periods[0] - 0.52, periods[-1] + 0.52))
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Generation (MW)")
    axes[0].legend(loc="upper left", ncol=3, frameon=False, fontsize=8)
    fig.savefig(FIGURE_DIR / "uc_dispatch.pdf")
    plt.close(fig)


def plot_convergence():
    fig, axes = plt.subplots(
        1, len(CASES), figsize=(7.0, 2.6), sharey=True, layout="constrained"
    )
    for ax, (name, title) in zip(axes, CASES):
        series = {}
        for method, _, _, _ in CONVERGENCE_METHODS:
            path = OUTPUT_DIR / f"{name}_{method}_results.json"
            with path.open(encoding="utf-8") as file:
                series[method] = json.load(file)["chp"]

        upper_bound = series["dw"]["upper_bound_eur"]
        for method, label, color, linestyle in CONVERGENCE_METHODS:
            gaps = [
                max(1e-3, upper_bound - value)
                for value in series[method]["dual_history_eur"]
            ]
            ax.loglog(range(1, len(gaps) + 1), gaps, label=label, color=color,
                      linestyle=linestyle, linewidth=1.35)
        ax.axhline(0.01, color="#767676", linewidth=0.7, linestyle=":")
        ax.set(title=title, xlabel="Dual evaluations", xlim=(0.9, 1120))
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Gap to DW upper bound (€)")
    axes[0].legend(loc="upper right", frameon=False, fontsize=7)
    fig.savefig(FIGURE_DIR / "convergence.pdf")
    plt.close(fig)


def main():
    results = load_results()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    with plt.rc_context({"font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "pdf.fonttype": 42}):
        plot_prices(results)
        plot_dispatch(results)
        if all((OUTPUT_DIR / f"{case}_level_results.json").exists() for case, _ in CASES):
            plot_prices(
                load_results("_level", "cutting_plane"), "CHP (level)", "ip_chp_prices.pdf"
            )
        if all(
            (OUTPUT_DIR / f"{case}_{method}_results.json").exists()
            for case, _ in CASES
            for method, _, _, _ in CONVERGENCE_METHODS
        ):
            plot_convergence()


if __name__ == "__main__":
    main()
