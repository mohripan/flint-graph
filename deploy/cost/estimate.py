"""What the planned deployment would cost per month, from the prices in prices.json.

Run it again after changing a size here or refreshing prices with fetch_prices.py:

    uv run python deploy/cost/estimate.py

These are list prices before tax and credits. Nothing here measures real usage yet.
"""

import json
from pathlib import Path

HOURS_PER_MONTH = 730

CONTROL = "t3a.medium"
CONTROL_ROOT_GB = 20
DATA_GB = 20
GPU = "g4dn.xlarge"
GPU_ROOT_GB = 70

# A visit is 15 minutes of use, then the 5 minute idle wait, plus an estimated 3 minute boot.
VISIT_MINUTES = 15 + 5 + 3
DAILY_CAP_HOURS = 3
HOURS_ON_FOR_DEMOS = 4


def main() -> None:
    prices = json.loads(Path(__file__).with_name("prices.json").read_text("utf-8"))
    hourly = prices["instances_usd_per_hour"]
    spot = {kind: row["median"] for kind, row in prices["spot_usd_per_hour_last_14_days"].items()}
    gp3 = prices["ebs_gp3_usd_per_gb_month"]
    ipv4 = prices["public_ipv4_usd_per_hour"]
    lightsail = prices["lightsail"]

    address = ipv4 * HOURS_PER_MONTH
    disks = (CONTROL_ROOT_GB + DATA_GB) * gp3
    gpu_disk = GPU_ROOT_GB * gp3
    on_demand = hourly[GPU] + ipv4
    interruptible = spot[GPU] + ipv4
    server = hourly[CONTROL] * HOURS_PER_MONTH
    fixed = {
        f"{CONTROL} always on": server,
        "Its public IP address": address,
        f"Its disks ({CONTROL_ROOT_GB} GB system + {DATA_GB} GB data)": disks,
        f"GPU server's disk while stopped ({GPU_ROOT_GB} GB)": gpu_disk,
    }

    print(f"Prices fetched {prices['fetched']} for {prices['region']}\n")
    print("Every month, even if nobody uses it, as prepared:\n")
    print("| Item | USD/month |\n| --- | ---: |")
    for name, cost in fixed.items():
        print(f"| {name} | {cost:.2f} |")
    print(f"| **Total** | **{sum(fixed.values()):.2f}** |\n")

    print(f"GPU options, per hour while running (a public IP adds {ipv4:.3f}):\n")
    print("| Type | GPU | On-demand | Spot, median of last 14 days | Runs poses and training? |")
    print("| --- | --- | ---: | ---: | --- |")
    notes = {
        "g4dn.xlarge": ("T4, 16 GB", "No: they refuse a GPU without native bf16"),
        "g6.xlarge": ("L4, 24 GB", "Yes"),
        "g5.xlarge": ("A10G, 24 GB", "Yes"),
    }
    for kind, (card, poses) in notes.items():
        print(f"| {kind} | {card} | {hourly[kind]:.3f} | {spot[kind]:.3f} | {poses} |")

    # (the always-on server's monthly cost, whether a disk and address are extra, GPU per hour)
    paths = {
        f"{CONTROL} on-demand, on all the time": (server, True, on_demand),
        f"{CONTROL} on-demand, on {HOURS_ON_FOR_DEMOS} h a day": (
            server * HOURS_ON_FOR_DEMOS / 24,
            True,
            on_demand,
        ),
        "t3a.small on-demand (2 GB), on all the time": (
            hourly["t3a.small"] * HOURS_PER_MONTH,
            True,
            on_demand,
        ),
        "Lightsail 2 GB, includes disk and address": (
            lightsail["small_3_2"]["usd_per_month"],
            False,
            on_demand,
        ),
        "Lightsail 4 GB, includes disk and address": (
            lightsail["medium_3_2"]["usd_per_month"],
            False,
            on_demand,
        ),
        f"{CONTROL} Spot and {GPU} Spot": (spot[CONTROL] * HOURS_PER_MONTH, True, interruptible),
    }
    visit = VISIT_MINUTES / 60
    print(f"\nWhole monthly bill with {GPU}, by usage:\n")
    print("| Always-on server | Nobody | 10 visits | 50 visits | 200 visits | One visit |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name, (cost, extras, gpu_hour) in paths.items():
        idle = cost + gpu_disk + (address + disks if extras else 0.0)
        row = [idle + count * visit * gpu_hour for count in (0, 10, 50, 200)]
        print(f"| {name} | " + " | ".join(f"{cell:.2f}" for cell in row), end="")
        print(f" | {visit * gpu_hour:.2f} |")

    cap = DAILY_CAP_HOURS * 30.0
    idle = sum(fixed.values())
    print(
        f"\nWorst case as prepared, the {DAILY_CAP_HOURS} h daily cap every day: "
        f"{idle + cap * on_demand:.2f} USD. The 100 USD of credits would last "
        f"{100 / (idle + 10 * visit * on_demand):.1f} months at 10 visits a month."
    )
    print(
        "\nSame-zone traffic between the servers is free. The first 100 GB out to the internet "
        f"each month is free, then {prices['egress_tiers'][0]['usd']:.3f} USD/GB."
    )


if __name__ == "__main__":
    main()
