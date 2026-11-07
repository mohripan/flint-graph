"""What the deployment costs per month, from the prices in prices.json and one measured visit.

Run it again after changing a size here or refreshing prices with fetch_prices.py:

    uv run python deploy/cost/estimate.py

These are list prices before tax and credits. The models run on Runpod (ADR 0078), and the AWS GPU
figures below that are only what the prepared but undeployed GPU server would cost.
"""

import json
from pathlib import Path

HOURS_PER_MONTH = 730

CONTROL = "t3.small"
CONTROL_ROOT_GB = 20
DATA_GB = 20
GPU = "g4dn.xlarge"
GPU_ROOT_GB = 70

# A visit is 15 minutes of use, then the 5 minute idle wait, plus an estimated 3 minute boot.
VISIT_MINUTES = 15 + 5 + 3
DAILY_CAP_HOURS = 3
HOURS_ON_FOR_DEMOS = 4

# From the Runpod endpoints and volume, read on 2026-11-07.
RUNPOD_WORKER_USD_PER_HOUR = 0.58
RUNPOD_VOLUME_GB = 25
RUNPOD_VOLUME_USD_PER_GB_MONTH = 0.07
# One whole creator run on the live site, including each worker's idle wait afterwards: three
# assistant turns, four sprites and a voice. See docs/reports/2026-11-07-models-on-runpod.md.
RUNPOD_VISIT_WORKER_SECONDS = 915 + 348


def what_runs_today(prices: dict) -> None:
    server = prices["instances_usd_per_hour"][CONTROL] * HOURS_PER_MONTH
    address = prices["public_ipv4_usd_per_hour"] * HOURS_PER_MONTH
    disks = (CONTROL_ROOT_GB + DATA_GB) * prices["ebs_gp3_usd_per_gb_month"]
    volume = RUNPOD_VOLUME_GB * RUNPOD_VOLUME_USD_PER_GB_MONTH
    idle = server + address + disks + volume
    visit = RUNPOD_VISIT_WORKER_SECONDS / 3600 * RUNPOD_WORKER_USD_PER_HOUR

    print("What runs today, every month even if nobody uses it:\n")
    print("| Item | USD/month |\n| --- | ---: |")
    print(f"| {CONTROL} always on | {server:.2f} |")
    print(f"| Its public IP address | {address:.2f} |")
    print(f"| Its disks ({CONTROL_ROOT_GB} GB system + {DATA_GB} GB data) | {disks:.2f} |")
    print(f"| Runpod volume holding the models ({RUNPOD_VOLUME_GB} GB) | {volume:.2f} |")
    print(f"| **Total** | **{idle:.2f}** |\n")
    print(f"One measured visit on Runpod: {visit:.2f} USD.\n")
    print("| Nobody | 10 visits | 50 visits | 200 visits |\n| ---: | ---: | ---: | ---: |")
    print("| " + " | ".join(f"{idle + count * visit:.2f}" for count in (0, 10, 50, 200)) + " |\n")


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
    what_runs_today(prices)
    print("The AWS GPU server, prepared but not deployed. Every month, as prepared:\n")
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
        f"{CONTROL} (2 GB), as prepared": (server, True, on_demand),
        "t3a.small (2 GB), needs the Paid Plan": (
            hourly["t3a.small"] * HOURS_PER_MONTH,
            True,
            on_demand,
        ),
        "Lightsail 2 GB, includes disk and address; refused on this account": (
            lightsail["small_3_2"]["usd_per_month"],
            False,
            on_demand,
        ),
        "t3a.medium Spot and g4dn Spot, needs an irreversible unlock": (
            spot["t3a.medium"] * HOURS_PER_MONTH,
            True,
            interruptible,
        ),
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
