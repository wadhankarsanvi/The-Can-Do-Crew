# validate_scenarios.py
"""Validate scenario YAML files for UrbanPulse project.
Checks:
- YAML syntax valid.
- Required top-level keys present.
- All domain values (events, decoys, feed_loss, contradictions) are in the canonical set.
- All referenced h3_cell IDs exist in the Nagpur H3 resolution-9 GeoJSON.
- feed_loss entries have domain within canonical set.
"""
import json, pathlib, sys
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

SCENARIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "eval" / "scenarios"
GEOJSON_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "nagpur_h3_res9.geojson"
CANONICAL_DOMAINS = {"power", "transit", "water", "health", "comms", "road"}

def load_geojson_cells(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {feat["properties"]["cell"] for feat in data.get("features", [])}

def validate_file(file_path, valid_cells):
    errors = []
    try:
        if _HAS_YAML:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                content = yaml.safe_load(f)
        else:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                content = json.load(f)
    except Exception as e:
        errors.append(f"Parsing error: {e}")
        return errors
    # required top-level keys
    required_keys = {"scenario_id", "family", "name", "description", "seed", "time_compression_factor", "events"}
    missing = required_keys - content.keys()
    if missing:
        errors.append(f"Missing top-level keys: {sorted(missing)}")
    # validate domains in events, decoys, feed_loss, contradictions
    def check_domain(item, context):
        domain = item.get("domain")
        if domain and domain not in CANONICAL_DOMAINS:
            errors.append(f"{context}: non-canonical domain '{domain}'")
    for ev in content.get("events", []):
        check_domain(ev, "event")
        cell = ev.get("h3_cell")
        if cell and cell not in valid_cells:
            errors.append(f"event h3_cell '{cell}' not found in geojson")
    for dec in content.get("decoys", []):
        check_domain(dec, "decoy")
        cell = dec.get("h3_cell")
        if cell and cell not in valid_cells:
            errors.append(f"decoy h3_cell '{cell}' not found in geojson")
    for fl in content.get("feed_loss", []):
        check_domain(fl, "feed_loss")
    for con in content.get("contradictions", []):
        ce = con.get("conflicting_event", {})
        check_domain(ce, "contradiction event")
        cell = ce.get("h3_cell")
        if cell and cell not in valid_cells:
            errors.append(f"contradiction h3_cell '{cell}' not found in geojson")
    return errors

def main():
    valid_cells = load_geojson_cells(GEOJSON_PATH)
    all_errors = {}
    for yaml_file in SCENARIO_DIR.glob("*.yaml"):
        errs = validate_file(yaml_file, valid_cells)
        if errs:
            all_errors[yaml_file.name] = errs
    # holdout subdir
    holdout_dir = SCENARIO_DIR / "holdout"
    for yaml_file in holdout_dir.glob("*.yaml"):
        errs = validate_file(yaml_file, valid_cells)
        if errs:
            all_errors[yaml_file.name] = errs
    if not all_errors:
        print("All scenario files validated successfully.")
    else:
        print("Validation issues found:")
        for fname, errs in all_errors.items():
            print(f"- {fname}:")
            for e in errs:
                print(f"    * {e}")

if __name__ == "__main__":
    main()
