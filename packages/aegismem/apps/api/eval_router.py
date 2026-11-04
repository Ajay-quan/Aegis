"""Evaluation endpoints."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends
from apps.api.dependencies import (
    get_ingest_service, get_retrieve_service, get_contradiction_service, get_db_store,
)
from domain.evaluations.evaluator import EvaluationRunner

logger = logging.getLogger(__name__)
eval_router = APIRouter()


@eval_router.post("/run", tags=["evaluation"])
async def run_evaluation(
    user_id_prefix: str = "eval",
    ingest=Depends(get_ingest_service),
    retrieve=Depends(get_retrieve_service),
    contradiction=Depends(get_contradiction_service),
    db=Depends(get_db_store),
):
    """Run the full evaluation suite."""
    runner = EvaluationRunner(ingest, retrieve, contradiction)
    report = await runner.run_full_eval(user_id_prefix=user_id_prefix)

    # Persist to DB
    try:
        await db.save_eval_result(
            eval_name=report.eval_name,
            run_id=report.run_id,
            metrics=report.to_dict(),
            config=report.config,
        )
    except Exception as e:
        logger.warning(f"Failed to save eval result: {e}")

    return report.to_dict()


@eval_router.post("/retrieval", tags=["evaluation"])
async def run_retrieval_eval(
    user_id: str = "eval_retrieval",
    k: int = 5,
    ingest=Depends(get_ingest_service),
    retrieve=Depends(get_retrieve_service),
    contradiction=Depends(get_contradiction_service),
):
    """Run retrieval-only evaluation."""
    runner = EvaluationRunner(ingest, retrieve, contradiction)
    metrics = await runner.run_retrieval_eval(user_id=user_id, k=k)
    return {
        "precision_at_k": metrics.precision_at_k,
        "recall_at_k": metrics.recall_at_k,
        "mrr": metrics.mrr,
        "latency_ms": metrics.latency_ms,
        "k": metrics.k,
    }


@eval_router.post("/contradiction", tags=["evaluation"])
async def run_contradiction_eval(
    user_id: str = "eval_contradiction",
    ingest=Depends(get_ingest_service),
    retrieve=Depends(get_retrieve_service),
    contradiction=Depends(get_contradiction_service),
):
    """Run contradiction detection evaluation."""
    runner = EvaluationRunner(ingest, retrieve, contradiction)
    metrics = await runner.run_contradiction_eval(user_id=user_id)
    return {
        "true_positives": metrics.true_positives,
        "false_positives": metrics.false_positives,
        "false_negatives": metrics.false_negatives,
        "precision": metrics.precision,
        "recall": metrics.recall,
        "f1": metrics.f1,
    }
