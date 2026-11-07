"""Fetch public AWS list prices into prices.json, so the estimate can be re-run and reviewed.

Read-only: the Price List API and Spot price history. It creates nothing and costs nothing.

    PYTHONUTF8=1 uv run python deploy/cost/fetch_prices.py --profile flintgraph
"""

import argparse
import datetime as dt
import json
import os
import shutil
import statistics
import subprocess
from pathlib import Path

REGION = "ap-southeast-2"
LOCATION = "Asia Pacific (Sydney)"
INSTANCES = (
    "t3a.small",
    "t3a.medium",
    "t3a.large",
    "t3.medium",
    "t4g.medium",
    "t4g.large",
    "m7i-flex.large",
    "g4dn.xlarge",
    "g5.xlarge",
    "g6.xlarge",
)
GPUS = ("g4dn.xlarge", "g5.xlarge", "g6.xlarge")
# The zone both servers are in. Spot prices differ between zones.
ZONE = "ap-southeast-2a"
SPOT_TYPES = ("t3a.small", "t3a.medium", *GPUS)
# Lightsail bundles, by the memory that matters here.
LIGHTSAIL = {"small_3_2", "medium_3_2"}


def aws_binary() -> str:
    found = shutil.which("aws")
    if found:
        return found
    return str(Path(os.environ["LOCALAPPDATA"]) / "Programs/Amazon/AWSCLIV2/aws.exe")


def aws(profile: str, region: str, *args: str) -> dict:
    done = subprocess.run(
        [aws_binary(), *args, "--region", region, "--profile", profile, "--output", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1", "AWS_PAGER": ""},
        check=True,
    )
    return json.loads(done.stdout)


def products(profile: str, service: str, **filters: str) -> list[dict]:
    args = ["pricing", "get-products", "--service-code", service, "--filters"]
    for field, value in filters.items():
        args.append(f"Type=TERM_MATCH,Field={field},Value={value}")
    rows: list[dict] = []
    token = None
    while True:
        page = aws(profile, "us-east-1", *args, *(["--next-token", token] if token else []))
        rows.extend(json.loads(item) for item in page["PriceList"])
        token = page.get("NextToken")
        if not token:
            return rows


def on_demand(row: dict) -> list[dict]:
    """The price dimensions of a product, with their usage ranges."""
    return [
        {
            "usd": float(dimension["pricePerUnit"]["USD"]),
            "unit": dimension["unit"],
            "begin": dimension.get("beginRange"),
            "end": dimension.get("endRange"),
            "description": dimension["description"],
        }
        for term in row["terms"]["OnDemand"].values()
        for dimension in term["priceDimensions"].values()
    ]


def instance_prices(profile: str) -> dict[str, float]:
    prices = {}
    for kind in INSTANCES:
        rows = products(
            profile,
            "AmazonEC2",
            instanceType=kind,
            location=LOCATION,
            operatingSystem="Linux",
            tenancy="Shared",
            preInstalledSw="NA",
            capacitystatus="Used",
        )
        paid = [dim["usd"] for row in rows for dim in on_demand(row) if dim["usd"] > 0]
        if paid:
            prices[kind] = min(paid)
    return prices


def spot_prices(profile: str) -> dict[str, dict[str, float]]:
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {}
    for kind in SPOT_TYPES:
        history = aws(
            profile,
            REGION,
            "ec2",
            "describe-spot-price-history",
            "--instance-types",
            kind,
            "--product-descriptions",
            "Linux/UNIX",
            "--availability-zone",
            ZONE,
            "--start-time",
            since,
        )["SpotPriceHistory"]
        values = [float(item["SpotPrice"]) for item in history]
        if values:
            result[kind] = {
                "median": statistics.median(values),
                "low": min(values),
                "high": max(values),
                "samples": len(values),
            }
    return result


def lightsail_prices(profile: str) -> dict[str, dict[str, float]]:
    bundles = aws(profile, REGION, "lightsail", "get-bundles")["bundles"]
    return {
        bundle["bundleId"]: {"usd_per_month": bundle["price"], "memory_gb": bundle["ramSizeInGb"]}
        for bundle in bundles
        if bundle["bundleId"] in LIGHTSAIL
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="flintgraph")
    args = parser.parse_args()
    profile = args.profile

    storage = products(profile, "AmazonEC2", location=LOCATION, volumeApiName="gp3")
    gp3 = [
        dim["usd"]
        for row in storage
        if row["product"]["productFamily"] == "Storage"
        for dim in on_demand(row)
    ]
    snapshot = [
        dim["usd"]
        for row in products(
            profile, "AmazonEC2", location=LOCATION, usagetype="APS2-EBS:SnapshotUsage"
        )
        for dim in on_demand(row)
    ]
    ipv4 = [
        dim["usd"]
        for row in products(profile, "AmazonVPC", location=LOCATION, group="VPCPublicIPv4Address")
        for dim in on_demand(row)
        if dim["usd"] > 0
    ]
    s3 = [
        dim
        for row in products(
            profile,
            "AmazonS3",
            location=LOCATION,
            volumeType="Standard",
            storageClass="General Purpose",
        )
        if row["product"]["productFamily"] == "Storage"
        for dim in on_demand(row)
    ]
    egress = [
        dim
        for row in products(
            profile,
            "AWSDataTransfer",
            fromLocation=LOCATION,
            transferType="AWS Outbound",
            toLocation="External",
        )
        for dim in on_demand(row)
    ]
    ecr = [
        dim["usd"]
        for row in products(profile, "AmazonECR", location=LOCATION)
        for dim in on_demand(row)
        if "GB-Mo" in dim["unit"] and dim["usd"] > 0
    ]
    prices = {
        "fetched": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
        "region": REGION,
        "instances_usd_per_hour": instance_prices(profile),
        "spot_usd_per_hour_last_14_days": spot_prices(profile),
        "lightsail": lightsail_prices(profile),
        "ebs_gp3_usd_per_gb_month": min(gp3),
        "ebs_snapshot_usd_per_gb_month": min(snapshot) if snapshot else None,
        "public_ipv4_usd_per_hour": min(ipv4) if ipv4 else None,
        "s3_standard_first_tier_usd_per_gb_month": max(item["usd"] for item in s3) if s3 else None,
        "egress_tiers": [
            {key: item[key] for key in ("usd", "begin", "end")}
            for item in sorted(egress, key=lambda item: float(item["begin"] or 0))
        ],
        "ecr_usd_per_gb_month": min(ecr) if ecr else None,
    }
    target = Path(__file__).with_name("prices.json")
    target.write_text(json.dumps(prices, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(prices, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
