# A GPU that sleeps

[ADR 0070](../adr/0070-a-gpu-that-sleeps.md) and [ADR 0069](../adr/0069-saying-when-the-gpu-is-asleep.md).
On a laptop you need none of this. `uv run python tools/narrative/studio.py` keeps working as it was.

**Not yet exercised on real AWS.** The EC2 calls have only run against a fake.

## What runs where

| Process | Machine | Settings |
| --- | --- | --- |
| API, frontend | always-on | |
| `narrative_gpu_dispatch` | always-on | `NARRATIVE_GPU_DISPATCH_ENABLED=true`, plus the API's database, Temporal, object-store and generation settings |
| `narrative_gpu_controller` | always-on | `NARRATIVE_GPU_CONTROLLER_ENABLED=true`, plus the settings below and an instance role |
| `narrative_{assistant,image,voice,pose,style,music}_worker` | GPU | Their usual settings, plus `NARRATIVE_GPU_EXECUTE_ONLY=true` |

All settings take the `FLINT_GRAPH_` prefix. Temporal and PostgreSQL must be reachable from the GPU machine.

## Controller settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `NARRATIVE_GPU_REGION` | required | AWS region of the machine |
| `NARRATIVE_GPU_INSTANCE_TAG` | required | `key=value` of the tag on exactly one instance |
| `NARRATIVE_GPU_INSTANCE_TYPE` | unset | The usual type. Needed for a fallback, and to return to it afterwards |
| `NARRATIVE_GPU_FALLBACK_INSTANCE_TYPE` | unset | Tried when the usual type has no capacity |
| `NARRATIVE_GPU_IDLE_SECONDS` | 300 | Nothing queued or running for this long stops it |
| `NARRATIVE_GPU_MAX_SESSION_SECONDS` | 14400 | Stops it however busy, and raises an alarm |
| `NARRATIVE_GPU_BOOT_GRACE_SECONDS` | 600 | Time to boot and load before silence counts |
| `NARRATIVE_GPU_SILENT_SECONDS` | 300 | Workers silent this long stops it, and raises an alarm |
| `NARRATIVE_GPU_DAILY_CAP_HOURS` | 8 | GPU hours per UTC day. Reached, it stays stopped and raises an alarm |

On the API, once the controller is running:

```text
FLINT_GRAPH_NARRATIVE_GPU_SLEEPS=true
FLINT_GRAPH_NARRATIVE_GPU_WAKE_SECONDS=<measured cold start>
```

Setting `SLEEPS` without a controller makes the Studio say "The GPU won't wake up", which would be true.

## IAM policy for the controller

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "ec2:DescribeInstances", "Resource": "*"},
    {
      "Effect": "Allow",
      "Action": ["ec2:StartInstances", "ec2:StopInstances", "ec2:ModifyInstanceAttribute"],
      "Resource": "arn:aws:ec2:REGION:ACCOUNT:instance/*",
      "Condition": {"StringEquals": {"aws:ResourceTag/KEY": "VALUE"}}
    }
  ]
}
```

Leave out `ec2:ModifyInstanceAttribute` if you set no fallback type.

## Alarms

The controller logs `gpu controller alarm: <reason>` at error level. Alarm on that line:

| Reason | Meaning |
| --- | --- |
| `session_too_long` | Ran past the max session. It was stopped; find out why it stayed busy |
| `heartbeat_stale` | Workers went silent. It was stopped; check the machine image and worker logs |
| `daily_cap` | Reached the daily GPU hours. Queued work waits for tomorrow, or raise the cap |
| `no_capacity` | The cloud had no machine. It keeps retrying; consider a fallback type |
| `instance_missing` | Tag matched no instance, or more than one. It touches nothing until that is fixed |

If the controller itself stops, its row goes stale and after 5 minutes the Studio says the GPU won't wake.

## Reading the state

`GET /v1/narrative/gpu` is what people see. In PostgreSQL, `narrative_gpu_status` has one row per worker
and one named `controller`. `narrative_gpu_sessions` has each launch and when it was last seen up.

## Trying it without AWS

The process split can be run on one machine: start one launcher with `STUDIO_SERVICES=api,preview,frontend`,
one with `dispatch`, and one with the workers and `FLINT_GRAPH_NARRATIVE_GPU_EXECUTE_ONLY=true`. A chat message
then waits with no worker running and runs when you start them.
