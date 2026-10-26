import argparse
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

import requests
import json
try:
    import yaml
except ImportError:
    yaml = None

# Import _make_event handling both package and script execution
if __package__:
    from ._sim_base import _make_event
else:
    # Running as a script, use direct import
    from _sim_base import _make_event


def _parse_offset(offset: str) -> int:
    """Parse T+30m, T+2h, or T+15s into seconds."""
    if not isinstance(offset, str) or not offset.startswith("T+"):
        raise ValueError(f"Invalid offset format: {offset!r}")

    value = offset[2:]
    if len(value) < 2:
        raise ValueError(f"Invalid offset format: {offset!r}")

    try:
        number = int(value[:-1])
    except ValueError as exc:
        raise ValueError(f"Invalid numeric offset: {offset}") from exc

    if number < 0:
        raise ValueError(f"Offset cannot be negative: {offset}")

    units = {"s": 1, "m": 60, "h": 3600}
    if value[-1] not in units:
        raise ValueError(f"Unsupported offset unit: {offset}")

    return number * units[value[-1]]


def _load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as file:
        if yaml:
            data = yaml.safe_load(file)
        else:
            data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Scenario YAML must contain a mapping.")

    return data


def _translate_event(
    event: Dict[str, Any],
    scenario_id: str,
    base_time: datetime,
    compression: float,
) -> Dict[str, Any]:
    timestamp = base_time + timedelta(
        seconds=_parse_offset(event["offset"]) / compression
    )

    return _make_event(
        domain=event["domain"],
        event_type=event["event_type"],
        entity_id=event["entity_id"],
        h3_cell=event["h3_cell"],
        severity=event["severity"],
        source_type=event["source_type"],
        scenario_tag=scenario_id,
        ts=timestamp,
    )


def _should_drop(
    event: Dict[str, Any],
    feed_loss: List[Dict[str, Any]],
    seed: Any,
) -> bool:
    """Apply deterministic fractional feed loss after each rule's offset."""
    for index, rule in enumerate(feed_loss):
        if rule.get("pattern") not in ("whole_domain", "domain"):
            continue
        if event.get("domain") != rule.get("domain"):
            continue
        if _parse_offset(event["offset"]) < _parse_offset(rule["offset"]):
            continue

        fraction = float(rule.get("fraction", 0))
        if not 0 <= fraction <= 1:
            raise ValueError(f"Invalid feed-loss fraction: {fraction}")

        key = (
            f"{seed}|{index}|{event.get('offset')}|{event.get('domain')}|"
            f"{event.get('event_type')}|{event.get('entity_id')}|"
            f"{event.get('h3_cell')}"
        )
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        sample = int(digest[:16], 16) / 0xFFFFFFFFFFFFFFFF

        if sample < fraction:
            return True

    return False


def run_scenario(
    scenario_path: str,
    api_base: str = "http://localhost:8000",
    dry_run: bool = False,
) -> Dict[str, int]:
    scenario = _load_yaml(scenario_path)
    scenario_id = scenario.get("scenario_id", "unknown")
    seed = scenario.get("seed", 0)

    try:
        compression = float(scenario.get("time_compression_factor", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("time_compression_factor must be numeric.") from exc

    if compression <= 0:
        raise ValueError("time_compression_factor must be greater than zero.")

    start_time = scenario.get("start_time")
    if start_time:
        base_dt = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=timezone.utc)
        else:
            base_dt = base_dt.astimezone(timezone.utc)
    else:
        # The seed is for deterministic behavior, not a Unix timestamp.
        base_dt = datetime.now(timezone.utc)

    timeline = []
    for event in scenario.get("events", []):
        timeline.append({"type": "causal", "event": event})
    for event in scenario.get("decoys", []):
        timeline.append({"type": "decoy", "event": event})
    for contradiction in scenario.get("contradictions", []):
        event = contradiction.get("conflicting_event")
        if event:
            timeline.append({"type": "contradiction", "event": event})

    timeline.sort(key=lambda item: _parse_offset(item["event"]["offset"]))
    feed_loss = scenario.get("feed_loss", []) or []

    accepted = rejected = dropped = dry_run_count = 0
    ingest_url = f"{api_base.rstrip('/')}/ingest"

    with requests.Session() as session:
        for item in timeline:
            event = item["event"]

            if _should_drop(event, feed_loss, seed):
                dropped += 1
                print(
                    f"[scenario_runner] Feed-loss dropped: "
                    f"{event['domain']} {event['event_type']} "
                    f"at {event['offset']}"
                )
                continue

            payload = _translate_event(
                event, scenario_id, base_dt, compression
            )

            if dry_run:
                print(
                    f"[dry-run] Would POST: {payload['domain']} "
                    f"{payload['event_type']} @ {payload['event_timestamp']}"
                )
                dry_run_count += 1
                continue

            try:
                response = session.post(ingest_url, json=payload, timeout=10)
                if 200 <= response.status_code < 300:
                    accepted += 1
                else:
                    rejected += 1
                    print(
                        f"[scenario_runner] Rejected "
                        f"({response.status_code}): {response.text}"
                    )
            except requests.RequestException as exc:
                rejected += 1
                print(f"[scenario_runner] Request failed: {exc}")

    summary = {
        "accepted": accepted,
        "rejected": rejected,
        "dropped": dropped,
        "dry_run": dry_run_count,
    }
    print(f"[scenario_runner] Summary: {summary}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scenario runner for UrbanPulse B2 evaluation"
    )
    parser.add_argument("scenario", help="Path to scenario YAML")
    parser.add_argument(
        "--api-base",
        default="http://localhost:8000",
        help="API base URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print events without sending requests",
    )
    args = parser.parse_args()
    run_scenario(args.scenario, api_base=args.api_base, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
