# ruff: noqa: E501
#!/usr/bin/env python3
"""Benchmark EPIC-010 ontology operations with deterministic fixtures.

The benchmark measures orchestration costs that should stay low even as the
Knowledge system grows: profile load, profile validation, candidate listing,
Nexus explorer seed, and the data-preparation portion of Enterprise Map render.
It intentionally uses deterministic fakes so parser/model/network variability
cannot mask regressions in the ontology workflow itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.append(str(ROOT / "tests" / "support"))

from ontology_lifecycle_fakes import DeterministicOntologyIngestor, FakeEmbedder, FakeEnterpriseGraph  # noqa: E402

from dashboard.knowledge.jobs import JobManager, JobState  # noqa: E402
from dashboard.knowledge.namespace import NamespaceManager  # noqa: E402
from dashboard.knowledge.service import KnowledgeService  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "ontology_lifecycle"


def measure(name: str, fn: Callable[[], Any]) -> tuple[str, float, Any]:
    started = time.perf_counter()
    result = fn()
    return name, (time.perf_counter() - started) * 1000, result


def wait_for_job(service: KnowledgeService, job_id: str) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        status = service.get_job(job_id)
        if status and status.state == JobState.COMPLETED:
            return
        if status and status.state in {JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}:
            raise RuntimeError(f"Import job ended in {status.state}: {status}")
        time.sleep(0.02)
    raise TimeoutError(f"Import job did not complete: {job_id}")


def build_service(tmp: Path) -> tuple[KnowledgeService, str]:
    nm = NamespaceManager(base_dir=tmp / "knowledge")
    service = KnowledgeService(namespace_manager=nm, job_manager=JobManager(base_dir=tmp / "knowledge", max_workers=1), embedder=FakeEmbedder())
    service._ingestor_override = DeterministicOntologyIngestor(service)  # noqa: SLF001
    namespace = "bench-ontology"
    service.create_namespace(namespace, description="Ontology operations benchmark")
    service.reset_default_ontology_profile(namespace)
    service.install_domain_pack(namespace, "financial-services", actor="benchmark")
    job_id = service.import_folder(namespace, str(FIXTURE_DIR.resolve()), actor="benchmark")
    wait_for_job(service, job_id)
    service._kuzu_graphs[namespace] = FakeEnterpriseGraph(service.get_ontology_profile(namespace))  # noqa: SLF001
    return service, namespace


def enterprise_map_data_prep(seed: dict[str, Any]) -> dict[str, int]:
    """Approximate frontend map prep by grouping lane and relation metadata."""
    lanes: dict[str, int] = {}
    families: dict[str, int] = {}
    for node in seed.get("nodes", []):
        lane = node.get("layer") or node.get("abstraction_level") or node.get("concept_type") or "unassigned"
        lanes[lane] = lanes.get(lane, 0) + 1
    for edge in seed.get("edges", []):
        family = edge.get("family") or "semantic"
        families[family] = families.get(family, 0) + 1
    return {"lane_count": len(lanes), "relationship_family_count": len(families)}


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ontology-bench-") as tmpdir:
        service, namespace = build_service(Path(tmpdir))
        profile = service.get_ontology_profile(namespace)
        measurements: list[dict[str, Any]] = []
        for name, elapsed_ms, result in [
            measure("profile_load", lambda: service.get_ontology_profile_with_default(namespace)),
            measure("profile_validation", lambda: service.validate_ontology_payload(namespace, {"subject": "profile", "profile": profile.model_dump(mode="json")})),
            measure("candidate_listing", lambda: service.list_ontology_candidates(namespace)),
            measure("explorer_seed", lambda: service.explorer_seed(namespace, top_k=3)),
        ]:
            measurements.append({"operation": name, "elapsed_ms": round(elapsed_ms, 3), "result_size": len(json.dumps(result, default=str))})
        seed = service.explorer_seed(namespace, top_k=3)
        name, elapsed_ms, result = measure("enterprise_map_data_prep", lambda: enterprise_map_data_prep(seed))
        measurements.append({"operation": name, "elapsed_ms": round(elapsed_ms, 3), "result": result})
        return {"namespace": namespace, "fixture": str(FIXTURE_DIR), "measurements": measurements}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit compact JSON instead of text table")
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print("Ontology operations benchmark")
    for item in result["measurements"]:
        print(f"{item['operation']}: {item['elapsed_ms']} ms")


if __name__ == "__main__":
    main()
