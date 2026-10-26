"""Standalone hosted generation coordinator; deliberately imports no rootIQ code.

Copied as generate.py into an explicitly reviewed public generator package. MATLAB is
invoked by MathWorks' licensed run-command action, not through a Python engine or shell.
Fitness and detector evaluation stay in the private/local rootIQ repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SENSORS = (
    "m_filt_WI101",
    "P_PI101",
    "P_PI102",
    "c_slurry_AI101",
    "L_cake_LI101",
    "V_slurry_LI101",
    "Tg_in_TI101",
    "Tg_out_TI102",
    "Vdryer_FI101",
)
SHARDS = 19


def digest(path: Path) -> str:
    """Hash bytes identically to the private adapter's provenance checks."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> Any:
    """Load explicit job/config files; never evaluate their contents as code."""
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    """Publish complete metadata atomically, rejecting NaN and infinity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def apply_simulator_modification(package: Path, settings: dict[str, Any]) -> dict[str, Any]:
    """Apply only the reviewed logging correction to an exact upstream file.

    Normalize line endings for cross-platform hashes. A changed patch or source fails
    before MATLAB starts; an already patched checkout must match the final hash.
    """
    modification = settings.get("simulator_modification")
    if not modification:
        return {}
    patch_path = confined(package, modification["patch_file"])
    if digest(patch_path) != modification["patch_sha256"]:
        raise ValueError("Simulator patch checksum differs from frozen campaign")
    patch = read_json(patch_path)
    for key in ("id", "target", "original_lf_sha256", "modified_lf_sha256"):
        if patch[key] != modification[key]:
            raise ValueError(f"Simulator patch metadata differs: {key}")
    target = confined(package / "external/ContCarSim", patch["target"])
    source = target.read_text(encoding="utf-8")
    checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if checksum == patch["modified_lf_sha256"]:
        return modification
    if checksum != patch["original_lf_sha256"]:
        raise ValueError("Simulator source differs from the reviewed upstream file")
    for replacement in patch["replacements"]:
        if source.count(replacement["before"]) != 1:
            raise ValueError("Simulator patch does not match exactly once")
        source = source.replace(replacement["before"], replacement["after"])
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != patch["modified_lf_sha256"]:
        raise ValueError("Modified simulator checksum differs from reviewed correction")
    target.write_bytes(source.encode("utf-8"))
    return modification


def confined(root: Path, name: str) -> Path:
    """Prevent untrusted artifact manifests from referencing files outside their root."""
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"Artifact path escapes recording directory: {name}")
    return path


def plan(settings: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    """Mirror the frozen campaign allocation without exposing engine implementation."""
    entries = []
    for group in settings[phase]:
        for offset in range(group["count"]):
            index = len(entries) + 1
            entries.append(
                {
                    "run_id": f"{'pilot' if phase == 'pilot' else 'cc'}{index:04d}",
                    "seed": group["seed_start"] + offset,
                    "scenario": group["scenario"],
                    "split": group["split"],
                    "role": "healthy" if group["scenario"] == 0 else "analysis",
                }
            )
    return entries


def validate_rows(path: Path, expected_rows: int) -> None:
    """Reject malformed CSVs without modifying any original values or time points."""
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        if next(reader, []) != ["elapsed_seconds", *SENSORS]:
            raise ValueError(f"Unexpected sensor schema: {path}")
        rows = list(reader)
    if len(rows) != expected_rows or len(rows) < 75:
        raise ValueError(f"Invalid run length: {path}")
    ranges = [[math.inf, -math.inf] for _ in SENSORS]
    for index, row in enumerate(rows):
        if len(row) != 10:
            raise ValueError(f"Invalid channel count: {path} row {index + 1}")
        values = [float(value) for value in row]
        if not all(math.isfinite(value) for value in values) or abs(values[0] - index) > 1e-9:
            raise ValueError(f"Non-finite values or irregular timestamps: {path} row {index + 1}")
        for bounds, value in zip(ranges, values[1:]):
            bounds[0], bounds[1] = min(bounds[0], value), max(bounds[1], value)
    if sum(high > low for low, high in ranges) < 2:
        raise ValueError(f"Fewer than two varying sensors: {path}")


def verify_approval(package: Path, pilot: Path, *, verify_files: bool) -> dict[str, Any]:
    """Bind locally verified fitness approval to this exact pilot and generator revision.

    The first workflow job verifies the actual artifact. Dependent shards receive its
    small verified manifest. This attestation is a repository-owner approval, not a
    replacement for rootIQ's private fitness computation or a cryptographic authority.
    """
    approval = read_json(package / "approvals/pilot.json")
    manifest = read_json(pilot / "manifest.json")
    if (
        approval.get("generation_gate_passed") is not True
        or approval.get("tau_max") != 3
        or approval.get("pilot_manifest_sha256") != digest(pilot / "manifest.json")
        or approval.get("campaign_sha256") != digest(package / "campaign.json")
        or approval.get("wrapper_sha256") != digest(package / "matlab/generate_campaign.m")
        or approval.get("pilot_run_id") != os.environ.get("PILOT_RUN_ID")
        or not re.fullmatch(r"[1-9][0-9]*", str(approval.get("pilot_run_id", "")))
    ):
        raise ValueError("No matching, locally verified pilot approval; full generation is forbidden")
    settings = read_json(package / "campaign.json")
    expected = [{key: item[key] for key in ("run_id", "seed", "role", "split")} for item in plan(settings, "pilot")]
    actual = [{key: item[key] for key in ("run_id", "seed", "role", "split")} for item in manifest["runs"]]
    if (
        manifest["phase"] != "pilot"
        or manifest["status"] != "complete"
        or actual != expected
        or manifest["revision"] != settings["revision"]
        or manifest["recipe"] != settings["recipe"]
        or manifest["campaign_sha256"] != approval["campaign_sha256"]
        or manifest["wrapper_sha256"] != approval["wrapper_sha256"]
        or manifest.get("simulator_modification", {}) != settings.get("simulator_modification", {})
        or manifest.get("hosted", {}).get("repository") != approval.get("pilot_repository")
        or manifest.get("hosted", {}).get("generator_revision") != approval.get("pilot_generator_revision")
    ):
        raise ValueError("Pilot provenance differs from approved campaign")
    if verify_files:
        for entry in manifest["runs"]:
            for key, hash_key in (("file", "sha256"), ("native_file", "native_sha256")):
                if digest(confined(pilot, entry[key])) != entry[hash_key]:
                    raise ValueError(f"Changed pilot file: {entry[key]}")
        for name, checksum in manifest["sidecar_sha256"].items():
            if digest(confined(pilot, name)) != checksum:
                raise ValueError(f"Changed pilot sidecar: {name}")
    count = len(manifest["runs"])
    pilot_bytes = sum(entry["file_bytes"] + entry["native_bytes"] for entry in manifest["runs"])
    estimate = {
        "pilot_recordings": count,
        "seconds_per_recording": manifest["elapsed_seconds"] / count,
        "estimated_shard_seconds_with_2x_headroom": manifest["elapsed_seconds"] / count * 10 * 2,
        "estimated_shard_bytes_with_2x_headroom": math.ceil(pilot_bytes / count * 10 * 2),
        "estimated_full_bytes": math.ceil(pilot_bytes / count * 190),
    }
    if estimate["estimated_shard_seconds_with_2x_headroom"] > 5 * 3600:
        raise ValueError("Pilot predicts a shard exceeding the five-hour compute budget; stop and review resources")
    return estimate


def prepare(package: Path, phase: str, shard: int | None, pilot: Path | None) -> Path:
    """Write exact MATLAB jobs; full shards require the previously verified pilot approval."""
    settings = read_json(package / "campaign.json")
    entries = plan(settings, phase)
    required_bytes = 1024**3
    if phase == "full":
        if shard is None or not 0 <= shard < SHARDS or pilot is None:
            raise ValueError("Full generation requires a shard index and verified pilot manifest")
        estimate = verify_approval(package, pilot, verify_files=False)
        required_bytes = max(required_bytes, estimate["estimated_shard_bytes_with_2x_headroom"])
        entries = entries[shard * 10 : (shard + 1) * 10]
    elif shard is not None:
        raise ValueError("Pilot recordings must not be split into independent campaigns")
    root = package / "output/data/raw/contcarsim"
    root = root / "pilot" if phase == "pilot" else root
    results = package / "output/results/contcarsim" / phase
    if shard is not None:
        results = results / f"shard-{shard:02d}"
    if (root / "runs").exists() or (root / "native").exists():
        raise ValueError("Refusing to overwrite existing recordings")
    simulator = package / "external/ContCarSim/simulator"
    license_file = simulator.parent / "LICENSE.txt"
    if not license_file.is_file():
        raise ValueError("Pinned upstream checkout is missing")
    modification = apply_simulator_modification(package, settings)
    for folder in (root / "runs", root / "native", results):
        folder.mkdir(parents=True, exist_ok=True)
    # Keep enough disk for at least the pilot plus logs before measuring actual usage.
    if shutil.disk_usage(package).free < required_bytes:
        raise ValueError(f"Insufficient free disk space: need {required_bytes} bytes including headroom")
    jobs = []
    for entry in entries:
        run_id = entry["run_id"]
        job_path = results / f"{run_id}.job.json"
        job = {
            "simulator_modification": modification,
            "mode": "generate",
            "recipe": settings["recipe"],
            "seed": entry["seed"],
            "scenario": entry["scenario"],
            "simulator_directory": str(simulator.resolve()),
            "sensor_file": str((root / f"runs/{run_id}.csv").resolve()),
            "native_file": str((root / f"native/{run_id}.mat").resolve()),
            "metadata_file": str((results / f"{run_id}.json").resolve()),
        }
        save_json(job_path, job)
        jobs.append(str(job_path.resolve()))
    index = {
        "phase": phase,
        "shard": shard,
        "entries": entries,
        "jobs": jobs,
        "data_directory": str(root.resolve()),
        "results_directory": str(results.resolve()),
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    path = package / "output/jobs.json"
    save_json(path, index)
    return path


def table(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    """Keep scenario and quality outputs outside sensor CSVs."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def collect(package: Path) -> Path:
    """Publish a complete pilot or shard only after every requested MATLAB job succeeded."""
    settings = read_json(package / "campaign.json")
    index = read_json(package / "output/jobs.json")
    root, results = Path(index["data_directory"]), Path(index["results_directory"])
    completed = read_json(results / "completed.json")
    modification = apply_simulator_modification(package, settings)
    if completed["completed"] != [item["run_id"] for item in index["entries"]]:
        raise ValueError("Incomplete campaign; partial files remain available for diagnosis")
    entries, labels, quality, runtimes = [], [], [], []
    for item in index["entries"]:
        run_id = item["run_id"]
        runtime = read_json(results / f"{run_id}.json")
        if read_json(results / f"{run_id}.job.json").get("simulator_modification", {}) != modification:
            raise ValueError(f"Simulator modification differs in job: {run_id}")
        sensor, native = root / f"runs/{run_id}.csv", root / f"native/{run_id}.mat"
        validate_rows(sensor, runtime["rows"])
        entry = {key: value for key, value in item.items() if key != "scenario"}
        entry.update(
            file=f"runs/{run_id}.csv",
            native_file=f"native/{run_id}.mat",
            rows=runtime["rows"],
            sha256=digest(sensor),
            native_sha256=digest(native),
            file_bytes=sensor.stat().st_size,
            native_bytes=native.stat().st_size,
        )
        entries.append(entry)
        labels.append(
            {
                "run_id": run_id,
                "scenario": item["scenario"],
                "activation_seconds": runtime["activation_seconds"] or "",
                "first_affected_sample": runtime["first_affected_sample"] or "",
            }
        )
        contents = runtime["final_content"]
        contents = contents if isinstance(contents, list) else [contents]
        if not contents or not all(
            type(value) in (int, float) and math.isfinite(value)
            for value in [*contents, runtime["total_production_kg"]]
        ):
            raise ValueError(f"Invalid native quality outputs: {run_id}")
        quality.extend(
            {
                "run_id": run_id,
                "cake": number,
                "ethanol_mass_fraction": value,
                "acceptable_at_upstream_limit": int(value <= 0.005),
                "total_production_kg": runtime["total_production_kg"],
            }
            for number, value in enumerate(contents, 1)
        )
        runtimes.append({key: runtime[key] for key in ("matlab_version", "release", "computer", "mex_extension")})
    if len({entry["sha256"] for entry in entries}) != len(entries):
        raise ValueError("Duplicate raw recordings; no replacement runs are permitted")
    table(root / "labels.csv", ["run_id", "scenario", "activation_seconds", "first_affected_sample"], labels)
    table(
        root / "quality.csv",
        ["run_id", "cake", "ethanol_mass_fraction", "acceptable_at_upstream_limit", "total_production_kg"],
        quality,
    )
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "phase": index["phase"],
        "recipe": settings["recipe"],
        "simulator_modification": modification,
        **{key: settings[key] for key in ("source_url", "revision", "license")},
        "license_sha256": digest(package / "external/ContCarSim/LICENSE.txt"),
        "campaign_sha256": digest(package / "campaign.json"),
        "wrapper_sha256": digest(package / "matlab/generate_campaign.m"),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": runtimes,
        "elapsed_seconds": completed["elapsed_seconds"],
        "runs": entries,
        "hosted": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "generator_revision": os.environ.get("GITHUB_SHA"),
            "shard": index["shard"],
        },
        "sidecar_sha256": {name: digest(root / name) for name in ("labels.csv", "quality.csv")},
    }
    name = "manifest.json" if index["phase"] == "pilot" else "part-manifest.json"
    path = root / name
    save_json(path, manifest)
    return path


def merge(package: Path, parts: Path) -> Path:
    """Assemble exactly 190 original recordings; any missing, duplicate or changed shard fails."""
    settings = read_json(package / "campaign.json")
    manifests = sorted(parts.glob("*/data/raw/contcarsim/part-manifest.json"))
    if len(manifests) != SHARDS:
        raise ValueError(f"Expected {SHARDS} complete shards, found {len(manifests)}")
    root = package / "output/data/raw/contcarsim"
    if root.exists():
        raise ValueError("Refusing to overwrite merged campaign")
    entries, labels, quality, runtimes, shard_ids, provenance = [], [], [], [], set(), None
    duration = 0.0
    for path in manifests:
        part = read_json(path)
        shard = part["hosted"]["shard"]
        if shard in shard_ids or shard not in range(SHARDS):
            raise ValueError("Duplicate or invalid shard identity")
        shard_ids.add(shard)
        identity = {
            key: part[key] for key in ("revision", "recipe", "campaign_sha256", "wrapper_sha256", "license_sha256")
        }
        identity["simulator_modification"] = part.get("simulator_modification", {})
        if provenance is not None and identity != provenance:
            raise ValueError("Shards have different simulator, recipe or generator provenance")
        if (
            part["revision"] != settings["revision"]
            or part["recipe"] != settings["recipe"]
            or part["campaign_sha256"] != digest(package / "campaign.json")
            or part["wrapper_sha256"] != digest(package / "matlab/generate_campaign.m")
            or part.get("simulator_modification", {}) != settings.get("simulator_modification", {})
        ):
            raise ValueError("Shard provenance differs from this generator's frozen configuration")
        provenance = identity
        logs = path.parents[3] / "results/contcarsim/full" / f"shard-{shard:02d}"
        if logs.is_dir():
            shutil.copytree(logs, package / "output/results/contcarsim/full" / f"shard-{shard:02d}")
        for entry in part["runs"]:
            for field, hash_field in (("file", "sha256"), ("native_file", "native_sha256")):
                source = confined(path.parent, entry[field])
                if digest(source) != entry[hash_field]:
                    raise ValueError(f"Changed shard recording: {entry['run_id']}")
                destination = confined(root, entry[field])
                if destination.exists():
                    raise ValueError(f"Duplicate recording path: {entry['run_id']}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        for name, target in (("labels.csv", labels), ("quality.csv", quality)):
            source = path.parent / name
            if digest(source) != part["sidecar_sha256"][name]:
                raise ValueError(f"Changed shard sidecar: {name}")
            with source.open(newline="", encoding="utf-8") as stream:
                target.extend(csv.DictReader(stream))
        entries.extend(part["runs"])
        runtimes.extend(part["runtime"])
        duration += part["elapsed_seconds"]
    entries.sort(key=lambda item: item["run_id"])
    expected = [{key: item[key] for key in ("run_id", "seed", "role", "split")} for item in plan(settings, "full")]
    actual = [{key: item[key] for key in ("run_id", "seed", "role", "split")} for item in entries]
    if actual != expected or len({item["sha256"] for item in entries}) != len(entries):
        raise ValueError("Merged recordings do not match the frozen 190-run campaign, or duplicate raw signals exist")
    for name, rows in (("labels.csv", labels), ("quality.csv", quality)):
        rows.sort(key=lambda item: (item["run_id"], int(item.get("cake", 0))))
        table(root / name, list(rows[0]), rows)
    manifest = {
        **part,
        "runs": entries,
        "runtime": runtimes,
        "elapsed_seconds": duration,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "hosted": {**part["hosted"], "shard": None, "shards": SHARDS},
        "sidecar_sha256": {name: digest(root / name) for name in ("labels.csv", "quality.csv")},
    }
    save_json(root / "manifest.json", manifest)
    return root / "manifest.json"


def main() -> int:
    """Coordinate actions and retain an explicit error artifact instead of claiming generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "collect", "verify-pilot", "merge"))
    parser.add_argument("--phase", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--shard", type=int)
    parser.add_argument("--pilot", type=Path)
    parser.add_argument("--parts", type=Path, default=Path("parts"))
    args = parser.parse_args()
    package = Path.cwd()
    try:
        if args.command == "prepare":
            print(prepare(package, args.phase, args.shard, args.pilot))
        elif args.command == "collect":
            print(collect(package))
        elif args.command == "verify-pilot":
            estimate = verify_approval(package, args.pilot, verify_files=True)
            save_json(package / "output/pilot-evidence/manifest.json", read_json(args.pilot / "manifest.json"))
            save_json(package / "output/resource-estimate.json", estimate)
        else:
            print(merge(package, args.parts))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        save_json(
            package / "output/hosted-failure.json",
            {"status": "failed", "command": args.command, "reason": str(exc), "replacement_runs": 0},
        )
        print(f"Generation stopped: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
