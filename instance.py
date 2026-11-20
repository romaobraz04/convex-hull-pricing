import pandas as pd

from pathlib import Path


class UCinstance:
    def __init__(self, instance_name):
        valid_instance_names = {
            "minimum_up_down",
            "network",
            "ramping",
            "single_period",
        }
        if instance_name not in valid_instance_names:
            raise ValueError(
                f"Invalid instance name {instance_name!r}. Expected one of: "
                f"{', '.join(sorted(valid_instance_names))}."
            )

        self.instance_name = instance_name
        self.demand, self.generators, self.reference = self._load_instance()
        self.periods = self.demand["period"].drop_duplicates().tolist()
        self.is_network = instance_name == "network"
        if self.is_network:
            data_dir = Path(__file__).resolve().parent / "data" / instance_name
            self.nodes = pd.read_csv(data_dir / "nodes.csv")
            self.lines = pd.read_csv(data_dir / "lines.csv")
            self.balance_keys = list(zip(self.demand["node"], self.demand["period"]))
            self.generator_nodes = self.generators["node"].tolist()
        else:
            self.balance_keys = [(None, period) for period in self.periods]
            self.generator_nodes = [None] * len(self.generators)
        self.balance_index = {key: i for i, key in enumerate(self.balance_keys)}
        self.generator_balance_indices = [
            [self.balance_index[node, period] for period in self.periods]
            for node in self.generator_nodes
        ]

    def _load_instance(self):
        # Load the instance data from a CSV file
        instance_dir = Path(__file__).resolve().parent / "data" / self.instance_name

        demand = pd.read_csv(instance_dir / "demand.csv").reset_index(drop=True)
        generators = pd.read_csv(
            instance_dir / "generators.csv", skipinitialspace=True
        ).reset_index(drop=True)
        generators.columns = generators.columns.str.strip()
        generators["generator"] = generators["generator"].str.strip()
        reference = pd.read_csv(instance_dir / "reference_dispatch.csv").reset_index(
            drop=True
        )

        return demand, generators, reference
