#!/usr/bin/env python3
"""Validate all scenario YAML files for correct schema.
Ensures:
- Canonical domains only: power, transit, water, health, comms, road
- Required top‑level fields present
- Each event contains required fields and valid H3 cell format (15 hex chars)
- feed_loss entries have required fields and valid domain
- YAML syntax is correct
"""
import os, sys, json, re

SCENARIO_ROOT = r"c:/Users/sanvi/OneDrive/Documents/The-Can-Do-Crew/eval/scenarios"
CANONICAL_DOMAINS = {"power", "transit", "water", "health", "comms", "road"}
H3_REGEX = re.compile(r"^[0-9a-f]{15}$")

errors = []

def add_error(msg):
    errors.append(msg)

def validate_event(event, path):
    required = ["offset", "domain", "event_type", "entity_id", "h3_cell", "severity", "source_type"]
    for f in required:
        if f not in event:
            add_error(f"Missing field '{f}' in event at {path}")
    domain = event.get("domain")
    if domain and domain not in CANONICAL_DOMAINS:
        add_error(f"Invalid domain '{domain}' in event at {path}")
    h3 = event.get("h3_cell")
    if h3 and not H3_REGEX.match(h3):
        add_error(f"Invalid H3 cell '{h3}' in event at {path}")

def validate_feed_loss(fl, path):
    required = ["offset", "pattern", "domain", "fraction"]
    for f in required:
        if f not in fl:
            add_error(f"Missing field '{f}' in feed_loss at {path}")
    domain = fl.get("domain")
    if domain and domain not in CANONICAL_DOMAINS:
        add_error(f"Invalid domain '{domain}' in feed_loss at {path}")

def validate_scenario(file_path):
    with open(file_path, "r", encoding="utf-8-sig") as f:
        try:
            data = json.load(f)
        except Exception as e:
            add_error(f"JSON syntax error in {file_path}: {e}")
            return
    # Top‑level required fields
    top_required = ["scenario_id", "family", "name", "description", "seed", "time_compression_factor", "events"]
    for f in top_required:
        if f not in data:
            add_error(f"Missing top‑level field '{f}' in {file_path}")
    # Events
    events = data.get("events", [])
    if not isinstance(events, list):
        add_error(f"'events' is not a list in {file_path}")
    else:
        for i, ev in enumerate(events):
            validate_event(ev, f"{file_path} events[{i}]")
    # Feed loss (optional)
    feed_loss = data.get("feed_loss", [])
    if not isinstance(feed_loss, list):
        add_error(f"'feed_loss' is not a list in {file_path}")
    else:
        for i, fl in enumerate(feed_loss):
            validate_feed_loss(fl, f"{file_path} feed_loss[{i}]")

for root, _, files in os.walk(SCENARIO_ROOT):
    if "ground_truth" in root:
        continue
    for name in files:
        if name.lower().endswith('.yaml'):
            validate_scenario(os.path.join(root, name))

if errors:
    print("Validation errors found:\n")
    for e in errors:
        print(f"- {e}")
    sys.exit(1)
else:
    print("All scenario files passed validation.")
    sys.exit(0)
