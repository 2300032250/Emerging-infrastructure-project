"""One-command reproducibility & acceptance harness (AC-1 to AC-4, KPI-1 to KPI-6, NT-1 to NT-5)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings, validate_startup_config
from app.db import SessionLocal, init_db
from app.services.assessment_service import ensure_seeded_and_trained
from app.services.evaluation_service import evaluate_acceptance_partition
from app.services.security_service import run_negative_test_campaign
from app.services.telemetry import inject_fault, recover_from_checkpoints


def main() -> None:
    validate_startup_config(settings)
    init_db()
    db = SessionLocal()
    try:
        ensure_seeded_and_trained(db)
        eval_summary = evaluate_acceptance_partition(db, trials=30)
        nt_campaign = run_negative_test_campaign(db)
        inject_fault(db, "acceptance_harness_simulated_fault")
        recovery = recover_from_checkpoints(db)

        report = {
            "use_case_id": settings.use_case_id,
            "team_batch": settings.team_batch,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config_version": settings.config_version,
            "config_hash": settings.config_hash,
            "model_seed": settings.model_seed,
            "evaluation": eval_summary,
            "negative_tests": {
                "all_passed": nt_campaign["all_passed"],
                "results": nt_campaign["results"],
            },
            "fault_recovery": recovery,
        }

        out_path = Path(__file__).resolve().parent / "data" / "acceptance_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"Acceptance report written to {out_path}")
        print(f"Negative tests all_passed={nt_campaign['all_passed']}")
        for kpi in eval_summary["kpis"]:
            print(f"  {kpi['kpi_id']}: {kpi['achieved']} {kpi['unit']} (O2={kpi['o2_reference']}) -> PASS={kpi['passed']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
