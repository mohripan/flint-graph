"""What the planned deployment would cost per month, from the prices in prices.json.

Run it again after changing a size here or refreshing prices with fetch_prices.py:

    uv run python deploy/cost/estimate.py

These are list prices before tax and credits. Nothing here measures real usage yet.
"""

import json
from pathlib import Path

HOURS_PER_MONTH = 730

CONTROL = "small_3_2"
GPU = "g4dn.xlarge"
GPU_ROOT_GB = 70
# What an EC2 server would need for the same job. Lightsail's price includes both.
EC2_DISKS_GB = 40

# A visit is 15 minutes of use, then the 5 minute idle wait, plus an estimated 3 minute boot.
VISIT_MINUTES = 15 + 5 + 3
DAILY_CAP_HOURS = 3


def main() -> None:
    prices = json.loads(Path(__file__).with_name("prices.json").read_text("utf-8"))
    hourly = prices["instances_usd_per_hour"]
    spot = {kind: row["median"] for kind, row in prices["spot_usd_per_hour_last_14_days"].items()}
    gp3 = prices["ebs_gp3_usd_per_gb_month"]
    ipv4 = prices["public_ipv4_usd_per_hour"]
    lightsail = prices["lightsail"]

    address = ipv4 * HOURS_PER_MONTH
    gpu_disk = GPU_ROOT_GB * gp3
    on_demand = hourly[GPU] + ipv4
    interruptible = spot[GPU] + ipv4
    ec2_extras = address + EC2_DISKS_GB * gp3
    plan = lightsail[CONTROL]["usd_per_month"]
    fixed = {
        f"Lightsail {lightsail[CONTROL]['memory_gb']:.0f} GB, with its disk and address": plan,
        f"GPU server's disk while stopped ({GPU_ROOT_GB} GB)": gpu_disk,
    }
    idle = sum(fixed.values())

    print(f"Prices fetched {prices['fetched']} for {prices['region']}\n")
    print("Every month, even if nobody uses it, as prepared:\n")
    print("| Item | USD/month |\n| --- | ---: |")
    for name, cost in fixed.items():
        print(f"| {name} | {cost:.2f} |")
    print(f"| **Total** | **{idle:.2f}** |\n")

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

    # (the always-on server's monthly cost including disk and address, GPU per hour)
    paths = {
        "Lightsail 2 GB, as prepared": (plan, on_demand),
        "Lightsail 4 GB": (lightsail["medium_3_2"]["usd_per_month"], on_demand),
        "t3a.small on-demand (2 GB)": (
            hourly["t3a.small"] * HOURS_PER_MONTH + ec2_extras,
            on_demand,
        ),
        "t3a.medium on-demand (4 GB)": (
            hourly["t3a.medium"] * HOURS_PER_MONTH + ec2_extras,
            on_demand,
        ),
        "t3a.medium Spot and g4dn Spot, needs an irreversible unlock": (
            spot["t3a.medium"] * HOURS_PER_MONTH + ec2_extras,
            interruptible,
        ),
    }
    visit = VISIT_MINUTES / 60
    print(f"\nWhole monthly bill with {GPU}, by usage:\n")
    print("| Always-on server | Nobody | 2 visits | 10 visits | 50 visits | One visit |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name, (cost, gpu_hour) in paths.items():
        row = [cost + gpu_disk + count * visit * gpu_hour for count in (0, 2, 10, 50)]
        print(f"| {name} | " + " | ".join(f"{cell:.2f}" for cell in row), end="")
        print(f" | {visit * gpu_hour:.2f} |")

    cap = DAILY_CAP_HOURS * 30.0
    print(
        f"\nWorst case as prepared, the {DAILY_CAP_HOURS} h daily cap every day: "
        f"{idle + cap * on_demand:.2f} USD. The 100 USD of credits would last "
        f"{100 / (idle + 2 * visit * on_demand):.1f} months at 2 visits a month."
    )
    print(
        "\nPrivate traffic between the servers in one zone is free. The GPU server's first 100 GB "
        f"out to the internet each month is free, then {prices['egress_tiers'][0]['usd']:.3f} "
        "USD/GB. Lightsail includes 1.5 TB of its own."
    )


if __name__ == "__main__":
    main()
