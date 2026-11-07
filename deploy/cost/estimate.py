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
DATA_GB = 40
GPU_ROOT_GB = 70
# Daily snapshots keep only what changed. An assumption until there is real data to measure.
SNAPSHOT_GB = 15

# A visit is 15 minutes of use, then the 5 minute idle wait, plus an estimated 3 minute boot.
VISIT_MINUTES = 15 + 5 + 3
DAILY_CAP_HOURS = 3
USAGE = {
    "nobody uses it": 0.0,
    "10 visits": 10 * VISIT_MINUTES / 60,
    "50 visits": 50 * VISIT_MINUTES / 60,
    "200 visits": 200 * VISIT_MINUTES / 60,
    f"worst case: {DAILY_CAP_HOURS} h cap every day": DAILY_CAP_HOURS * 30.0,
}
GPUS = ("g4dn.xlarge", "g6.xlarge", "g5.xlarge")


def main() -> None:
    prices = json.loads(Path(__file__).with_name("prices.json").read_text("utf-8"))
    hourly = prices["instances_usd_per_hour"]
    gp3 = prices["ebs_gp3_usd_per_gb_month"]
    ipv4 = prices["public_ipv4_usd_per_hour"]

    fixed = {
        f"{CONTROL} always on": hourly[CONTROL] * HOURS_PER_MONTH,
        "Its public IP address": ipv4 * HOURS_PER_MONTH,
        f"Its disks ({CONTROL_ROOT_GB} GB system + {DATA_GB} GB data)": (CONTROL_ROOT_GB + DATA_GB)
        * gp3,
        f"Daily backups (about {SNAPSHOT_GB} GB of snapshots)": SNAPSHOT_GB
        * prices["ebs_snapshot_usd_per_gb_month"],
        f"GPU server's disk while stopped ({GPU_ROOT_GB} GB)": GPU_ROOT_GB * gp3,
    }
    total = sum(fixed.values())

    print(f"Prices fetched {prices['fetched']} for {prices['region']}\n")
    print("Every month, even if nobody uses it:\n")
    print("| Item | USD/month |\n| --- | ---: |")
    for name, cost in fixed.items():
        print(f"| {name} | {cost:.2f} |")
    print(f"| **Total** | **{total:.2f}** |\n")

    print(f"GPU options, per hour while running (a public IP adds {ipv4:.3f}):\n")
    print("| Type | GPU | On-demand | Spot, median of last 14 days | Runs poses and training? |")
    print("| --- | --- | ---: | ---: | --- |")
    notes = {
        "g4dn.xlarge": ("T4, 16 GB", "No: they refuse a GPU without native bf16"),
        "g6.xlarge": ("L4, 24 GB", "Yes"),
        "g5.xlarge": ("A10G, 24 GB", "Yes"),
    }
    spot = prices["spot_usd_per_hour_last_14_days"]
    for gpu in GPUS:
        card, poses = notes[gpu]
        print(f"| {gpu} | {card} | {hourly[gpu]:.3f} | {spot[gpu]['median']:.3f} | {poses} |")

    print("\nWhole monthly bill, on-demand:\n")
    print("| Usage | GPU hours | " + " | ".join(GPUS) + " |")
    print("| --- | ---: | " + " | ".join("---:" for _ in GPUS) + " |")
    for name, hours in USAGE.items():
        costs = [total + hours * (hourly[gpu] + ipv4) for gpu in GPUS]
        print(f"| {name} | {hours:.1f} | " + " | ".join(f"{cost:.2f}" for cost in costs) + " |")

    visit_hours = VISIT_MINUTES / 60
    print("\nOne 15 minute visit costs, in GPU time alone:\n")
    for gpu in GPUS:
        print(f"- {gpu}: {visit_hours * (hourly[gpu] + ipv4):.2f} USD")

    print("\nOther choices:\n")
    print("| Choice | Change, USD/month |\n| --- | ---: |")
    print(
        f"| t3a.small (2 GB, same CPU allowance) instead of {CONTROL} (4 GB) | "
        f"{(hourly['t3a.small'] - hourly[CONTROL]) * HOURS_PER_MONTH:.2f} |"
    )
    print(
        f"| t3a.large (8 GB) instead of {CONTROL} (4 GB) | "
        f"+{(hourly['t3a.large'] - hourly[CONTROL]) * HOURS_PER_MONTH:.2f} |"
    )
    print(
        f"| t4g.medium (Arm, needs Arm images) instead of {CONTROL} | "
        f"{(hourly['t4g.medium'] - hourly[CONTROL]) * HOURS_PER_MONTH:.2f} |"
    )
    s3 = prices["s3_standard_first_tier_usd_per_gb_month"]
    print(f"| Each 10 GB of art on S3 instead of the server's disk | {(s3 - gp3) * 10:.2f} |")
    print(f"| Each 10 GB more GPU disk (music, poses, more voices) | +{gp3 * 10:.2f} |")

    credits = 100.0
    light = total + USAGE["10 visits"] * (hourly["g6.xlarge"] + ipv4)
    print(
        f"\nThe {credits:.0f} USD of credits would last {credits / light:.1f} months "
        "at 10 visits a month on g6.xlarge."
    )
    print(
        "\nSame-zone traffic between the servers is free. The first 100 GB out to the internet "
        "each month is free, then "
        f"{prices['egress_tiers'][0]['usd']:.3f} USD/GB."
    )


if __name__ == "__main__":
    main()
