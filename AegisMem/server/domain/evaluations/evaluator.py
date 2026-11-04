"""AegisMem evaluation framework — multi-K metrics, nDCG, dual-layer evaluation.

Supports four benchmark modes:
  SANITY   — small quick smoke test (first 10 pairs)
  EXPANDED — full 50-pair synthetic benchmark
  HARD     — expanded + hard negatives + paraphrased queries
  CONTRADICTION — contradiction detection only
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EvalMode(str, Enum):
    SANITY = "sanity"
    EXPANDED = "expanded"
    HARD = "hard"
    CONTRADICTION = "contradiction"


# ---------------------------------------------------------------------------
# Metric types
# ---------------------------------------------------------------------------


@dataclass
class RetrievalMetrics:
    precision_at_1: float = 0.0
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0
    recall_at_1: float = 0.0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    f1_at_1: float = 0.0
    f1_at_3: float = 0.0
    f1_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    latency_ms: float = 0.0
    total_queries: int = 0
    total_memories: int = 0


@dataclass
class ContradictionMetrics:
    true_positives: int = 0
    true_negatives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    total_pairs: int = 0


@dataclass
class UpdateMetrics:
    correct_actions: int = 0
    total_cases: int = 0
    accuracy: float = 0.0
    version_integrity: float = 0.0


@dataclass
class EvaluationReport:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    eval_name: str = ""
    eval_mode: str = "expanded"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    contradiction: ContradictionMetrics = field(default_factory=ContradictionMetrics)
    update: UpdateMetrics = field(default_factory=UpdateMetrics)
    config: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "eval_name": self.eval_name,
            "eval_mode": self.eval_mode,
            "retrieval": {
                "P@1": self.retrieval.precision_at_1,
                "P@3": self.retrieval.precision_at_3,
                "P@5": self.retrieval.precision_at_5,
                "R@1": self.retrieval.recall_at_1,
                "R@3": self.retrieval.recall_at_3,
                "R@5": self.retrieval.recall_at_5,
                "F1@1": self.retrieval.f1_at_1,
                "F1@3": self.retrieval.f1_at_3,
                "F1@5": self.retrieval.f1_at_5,
                "MRR": self.retrieval.mrr,
                "nDCG@5": self.retrieval.ndcg_at_5,
                "latency_ms": self.retrieval.latency_ms,
                "total_queries": self.retrieval.total_queries,
                "total_memories": self.retrieval.total_memories,
            },
            "contradiction": {
                "precision": self.contradiction.precision,
                "recall": self.contradiction.recall,
                "f1": self.contradiction.f1,
                "total_pairs": self.contradiction.total_pairs,
            },
        }


# ---------------------------------------------------------------------------
# nDCG helper
# ---------------------------------------------------------------------------

def _compute_ndcg(ranked_relevances: list[int], ideal_count: int, k: int) -> float:
    """Compute Normalized Discounted Cumulative Gain at k."""
    dcg = sum(
        rel / math.log2(i + 2) for i, rel in enumerate(ranked_relevances[:k])
    )
    # Ideal: first `ideal_count` slots are relevant.
    ideal = sorted(ranked_relevances, reverse=True)[:k]
    # Pad ideal if fewer relevant items than k.
    while len(ideal) < min(k, ideal_count):
        ideal.append(1)
    idcg = sum(
        rel / math.log2(i + 2) for i, rel in enumerate(ideal)
    )
    return dcg / idcg if idcg > 0 else 0.0


# ---------------------------------------------------------------------------
# Synthetic dataset generator — realistic, challenging data
# ---------------------------------------------------------------------------


class SyntheticDatasetGenerator:
    """Generates synthetic memory datasets for evaluation.

    Designed to be challenging enough to produce realistic (non-perfect) scores
    by including semantically similar distractors and nuanced boundary cases.
    """

    # Each tuple: (memory_content, query, relevant_group_id)
    USER_FACTS = [
        # --- Personal Preferences ---
        ("user likes Python programming and uses it for backend development", "What programming language does the user prefer?", "prog_lang"),
        ("user enjoys TypeScript for frontend projects", "What does the user use for frontend?", "frontend"),
        ("user prefers dark mode in all applications", "What is the user's UI theme preference?", "ui_pref"),
        ("user prefers vim keybindings in VS Code", "What editor setup does the user use?", "editor"),
        ("user likes mechanical keyboards with Cherry MX Brown switches", "What kind of keyboard does the user use?", "keyboard"),

        # --- Work / Career ---
        ("user works at Acme Corp as a senior backend engineer", "Where does the user work?", "workplace"),
        ("user has 8 years of professional software engineering experience", "How much experience does the user have?", "experience"),
        ("user's manager at Acme Corp is named Sarah Chen", "Who is the user's manager?", "manager"),
        ("user is considering switching to a startup in the AI space", "Is the user looking for a new job?", "job_search"),
        ("user previously worked at Google for 3 years on cloud infrastructure", "Where did the user work before?", "prev_job"),

        # --- Health / Medical ---
        ("user is allergic to peanuts and tree nuts", "What food allergies does the user have?", "allergy"),
        ("user is lactose intolerant and avoids dairy products", "Does the user have any dietary restrictions?", "dietary"),
        ("user takes daily vitamin D supplements", "What supplements does the user take?", "supplements"),
        ("user runs 5km every morning before work", "What is the user's exercise routine?", "exercise"),
        ("user has a yearly physical checkup scheduled for April", "When is the user's next doctor appointment?", "medical_appt"),

        # --- Relationships ---
        ("user's wife is named Maria and she works as a nurse", "What is the user's spouse's name?", "spouse"),
        ("user has two children: Emma (age 7) and Liam (age 4)", "Does the user have children?", "children"),
        ("user's best friend Jake lives in Portland", "Who is the user's best friend?", "best_friend"),
        ("user's parents live in Chicago and visit every Thanksgiving", "Where do the user's parents live?", "parents"),
        ("user has a golden retriever named Max", "Does the user have any pets?", "pet"),

        # --- Location / Travel ---
        ("user lives in San Francisco in the Mission District", "Where does the user live?", "location"),
        ("user is planning a trip to Japan in October", "What travel plans does the user have?", "travel_plan"),
        ("user visited Italy last summer and loved Florence", "Has the user traveled to Europe recently?", "past_travel"),
        ("user commutes to work by BART train", "How does the user get to work?", "commute"),

        # --- Technical Skills ---
        ("user is learning Rust programming on weekends", "What new technologies is the user learning?", "learning"),
        ("user is experienced with PostgreSQL and Redis databases", "What databases does the user know?", "databases"),
        ("user uses Docker and Kubernetes for deployment", "What deployment tools does the user use?", "devops"),
        ("user is familiar with React and Next.js frameworks", "What frontend frameworks does the user know?", "frontend_fw"),
        ("user writes unit tests using pytest", "What testing framework does the user use?", "testing"),

        # --- Hobbies / Personal ---
        ("user's favorite book is Dune by Frank Herbert", "What is the user's favorite book?", "fav_book"),
        ("user enjoys cooking Italian food on weekends", "What does the user do for fun?", "hobby_cooking"),
        ("user plays acoustic guitar and is learning jazz chords", "Does the user play any instruments?", "music"),
        ("user watches Formula 1 racing and supports McLaren", "What sports does the user follow?", "sports"),
        ("user reads sci-fi novels before bed most nights", "What kind of books does the user read?", "reading"),

        # --- Communication / Work Style ---
        ("user prefers async communication over synchronous meetings", "What communication style does the user prefer?", "comm_style"),
        ("user blocks off mornings for deep work with no meetings", "When does the user do focused work?", "deep_work"),
        ("user uses Notion for personal project management", "What productivity tools does the user use?", "tools"),
        ("user has a daily standup at 9:30am Pacific time", "When does the user have meetings?", "meetings"),

        # --- Financial ---
        ("user has a 401k through Acme Corp with Fidelity", "What retirement accounts does the user have?", "retirement"),
        ("user is saving for a down payment on a house", "What is the user saving for?", "savings_goal"),
        ("user uses YNAB for personal budgeting", "How does the user track finances?", "budgeting"),

        # --- Education ---
        ("user graduated from MIT with a BS in Computer Science in 2016", "Where did the user go to college?", "education"),
        ("user completed Andrew Ng's machine learning course on Coursera", "Has the user taken ML courses?", "ml_course"),

        # --- Schedules / Routines ---
        ("user wakes up at 6am every weekday", "What time does the user wake up?", "wake_time"),
        ("user meal preps on Sunday afternoons for the week", "When does the user prepare food?", "meal_prep"),
        ("user has a weekly 1-on-1 with his manager every Thursday at 2pm", "When does the user meet with his manager?", "one_on_one"),
        ("user attends a book club that meets on the first Wednesday of each month", "Does the user participate in any groups?", "book_club"),

        # --- Multi-fact queries (queries that match multiple facts) ---
        ("user is skilled in Python, Go, and SQL", "What programming languages does the user know?", "prog_lang"),
        ("user has a severe shellfish allergy diagnosed in childhood", "What food allergies does the user have?", "allergy"),
        ("user enjoys hiking in Marin County on weekends", "What does the user do for fun?", "hobby_cooking"),
    ]

    # Hard distractors — semantically close but NOT the correct answer.
    NOISE_FACTS = [
        "user's coworker recommended learning Go for systems programming",
        "user read a blog post comparing Python vs Rust performance",
        "user attended a JavaScript conference last year but didn't enjoy it",
        "user debugged a C++ memory leak for a colleague",
        "user bookmarked a tutorial on Swift but hasn't started it",
        "user's friend works at Microsoft as a PM",
        "user had a phone interview with Stripe but decided not to proceed",
        "user met someone from Acme Corp's marketing team at a conference",
        "user's college roommate started a company called TechCorp",
        "user read about Acme Corp's recent IPO filing",
        "user bought a jar of peanut butter for a friend's party",
        "user's daughter Emma has a mild egg allergy",
        "user tried a lactose-free cheese brand and found it acceptable",
        "user read about the benefits of vitamin C supplements",
        "user's gym friend recommended a new protein powder",
        "user visited San Francisco for a tech conference in 2019",
        "user's sister recently moved to San Francisco's Financial District",
        "user considered moving to Austin but decided against it",
        "user took a weekend road trip to Lake Tahoe",
        "user mentioned a colleague named Maria who works in HR",
        "user babysat his nephew over the weekend",
        "user's neighbor has a dog named Buddy that plays with Max",
        "user's friend Jake recommended a restaurant in San Francisco",
        "user received a cookbook as a birthday gift but hasn't opened it",
        "user watched a documentary about Formula 1 racing history",
        "user's wife Maria plays piano and practices jazz standards",
        "user downloaded a guitar tuner app but rarely uses it",
        "user complained about too many Slack notifications",
        "user tried Todoist but switched back to Notion",
        "user attended a productivity workshop on time blocking",
        "user's team is experimenting with async standups",
        "user's college friend studied at Stanford in the same year",
        "user watched a YouTube video about MIT's latest AI research",
        "user considered taking a Coursera course on deep learning",
        "user's intern asked for advice on learning machine learning",
        "user's alarm went off at 6am but he snoozed for 30 minutes once",
        "user skipped meal prep last Sunday due to a headache",
        "user rescheduled his Thursday meeting once due to a conflict",
        "user mentioned he had a busy week at work",
        "user said the weather in San Francisco has been unusually warm",
        "user updated his LinkedIn profile last month",
        "user installed a new app on his phone",
        "user ordered new office supplies from Amazon",
    ]

    # Hard negatives — paraphrased or indirect queries for HARD mode.
    HARD_QUERIES = [
        ("Tell me about the user's coding background", "prog_lang"),
        ("What does the user do professionally?", "workplace"),
        ("Any health issues I should know about?", "allergy"),
        ("Who are the important people in the user's life?", "spouse"),
        ("Where is the user based?", "location"),
        ("What side projects does the user work on?", "learning"),
        ("How does the user stay organized?", "tools"),
        ("What are the user's financial priorities?", "savings_goal"),
        ("Tell me about the user's daily routine", "wake_time"),
        ("What does the user enjoy outside of work?", "hobby_cooking"),
    ]

    CONTRADICTIONS = [
        # --- TRUE CONTRADICTIONS: Obvious ---
        ("user lives in San Francisco", "user moved to New York last month and settled in Brooklyn", True),
        ("user works at Acme Corp as a senior engineer", "user recently joined Beta Corp as their new CTO", True),
        ("user is deathly allergic to ALL nuts including peanuts", "user ate a peanut butter sandwich for lunch today", True),
        ("user is a strict vegan who never eats animal products", "user ordered a steak dinner at the restaurant last night", True),
        # --- TRUE CONTRADICTIONS: Moderate ---
        ("user always works from home and never goes to the office", "user commutes to the downtown office every weekday by train", True),
        ("user hates coffee and never drinks it", "user drinks three cups of espresso every morning", True),
        ("user is single and not currently in a relationship", "user's wife Maria surprised him with a birthday cake", True),
        ("user has never traveled outside the United States", "user returned from a two-week vacation in Japan last month", True),
        # --- TRUE CONTRADICTIONS: Subtle ---
        ("user is a morning person who wakes up at 5am every day", "user typically stays up until 3am and sleeps until noon", True),
        ("user exclusively uses Mac computers and refuses to use Windows", "user set up a new Windows desktop for his home gaming setup", True),
        ("user completed his PhD in Physics from Stanford in 2020", "user graduated from MIT with a BS in Computer Science and never pursued graduate school", True),
        # --- NOT CONTRADICTIONS: Obvious ---
        ("user likes Python programming", "user also enjoys TypeScript for frontend work", False),
        ("user works at Acme Corp", "user attended a networking event hosted by Google", False),
        ("user runs every morning", "user also does yoga on weekends", False),
        ("user lives in San Francisco", "user spent the weekend visiting friends in Los Angeles", False),
        # --- NOT CONTRADICTIONS: Moderate ---
        ("user is a vegetarian who doesn't eat meat", "user bought a leather jacket last week", False),
        ("user prefers dark mode in all applications", "user switched to light mode briefly to show a presentation", False),
        ("user only codes in Python for backend work", "user wrote a bash script to automate his deployment pipeline", False),
        ("user doesn't drink alcohol", "user bought a bottle of wine as a gift for his friend's birthday", False),
        # --- NOT CONTRADICTIONS: Hard ---
        ("user said he doesn't like social media", "user posted a photo on LinkedIn to celebrate a work anniversary", False),
        ("user prefers working alone on complex problems", "user led a team brainstorming session on the new project architecture", False),
        ("user has been using the same phone for 4 years", "user browsed new phone models on Apple's website", False),
        ("user is saving aggressively and avoids unnecessary spending", "user spent $200 on a birthday dinner for his wife", False),
        ("user studies Japanese in his free time", "user struggled to read a Japanese restaurant menu", False),
        # --- TEMPORAL ---
        ("user drives a 2018 Honda Civic", "user bought a brand new Tesla Model 3 and sold his old car", True),
        ("user's favorite programming language is Java", "user said he now considers Python his absolute favorite language and doesn't enjoy Java anymore", True),
    ]

    UPDATE_CASES = [
        {"existing": "user lives in Seattle", "new": "user moved to Austin, Texas", "expected_action": "supersede"},
        {"existing": "user likes coffee", "new": "user loves coffee especially espresso", "expected_action": "update"},
        {"existing": "user works at Acme Corp", "new": "user had lunch at a burger place", "expected_action": "create"},
        {"existing": "user prefers dark mode", "new": "user prefers dark mode in all apps", "expected_action": "skip"},
    ]

    def get_retrieval_dataset(self, mode: EvalMode = EvalMode.EXPANDED) -> list[dict[str, Any]]:
        """Return retrieval dataset. Mode controls size."""
        items = [
            {"memory": fact, "query": query, "group_id": group_id}
            for fact, query, group_id in self.USER_FACTS
        ]
        if mode == EvalMode.SANITY:
            return items[:10]
        return items

    def get_noise_facts(self, mode: EvalMode = EvalMode.EXPANDED) -> list[str]:
        if mode == EvalMode.SANITY:
            return self.NOISE_FACTS[:5]
        return list(self.NOISE_FACTS)

    def get_hard_queries(self) -> list[dict[str, Any]]:
        return [
            {"query": q, "group_id": gid} for q, gid in self.HARD_QUERIES
        ]

    def get_contradiction_dataset(self) -> list[dict[str, Any]]:
        return [
            {"memory_a": a, "memory_b": b, "is_contradiction": expected}
            for a, b, expected in self.CONTRADICTIONS
        ]

    def get_update_dataset(self) -> list[dict[str, Any]]:
        return self.UPDATE_CASES


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------


class EvaluationRunner:
    """Runs evaluation suites against the AegisMem system."""

    def __init__(self, ingest_svc: Any, retrieve_svc: Any, contradiction_svc: Any) -> None:
        self._ingest = ingest_svc
        self._retrieve = retrieve_svc
        self._contradiction = contradiction_svc
        self._dataset = SyntheticDatasetGenerator()

    async def run_retrieval_eval(
        self,
        user_id: str = "eval_user",
        k_values: list[int] | None = None,
        mode: EvalMode = EvalMode.EXPANDED,
    ) -> RetrievalMetrics:
        """Evaluate retrieval quality with multi-K metrics and nDCG."""
        k_values = k_values or [1, 3, 5]
        max_k = max(k_values)

        dataset = self._dataset.get_retrieval_dataset(mode)
        noise_facts = self._dataset.get_noise_facts(mode)
        logger.info(f"Running retrieval eval ({mode.value}): {len(dataset)} memories + {len(noise_facts)} noise")

        # Ingest all memories.
        memory_ids = []
        for item in dataset:
            mem = await self._ingest.ingest_text(
                text=item["memory"], user_id=user_id, session_id="eval",
            )
            memory_ids.append(mem.memory_id)

        for noise in noise_facts:
            await self._ingest.ingest_text(text=noise, user_id=user_id, session_id="noise")

        await asyncio.sleep(0.1)

        # Build group_id → set of memory_ids.
        group_to_ids: dict[str, set[str]] = {}
        for i, item in enumerate(dataset):
            gid = item["group_id"]
            group_to_ids.setdefault(gid, set()).add(memory_ids[i])

        # Deduplicate queries.
        seen: set[str] = set()
        unique_queries: list[dict[str, Any]] = []
        for item in dataset:
            if item["query"] not in seen:
                seen.add(item["query"])
                unique_queries.append(item)

        # Add hard queries in HARD mode.
        if mode == EvalMode.HARD:
            for hq in self._dataset.get_hard_queries():
                if hq["query"] not in seen:
                    seen.add(hq["query"])
                    unique_queries.append(hq)

        from core.schemas.memory import RetrievalQuery

        # Collect per-query metrics at each k.
        precision_at: dict[int, list[float]] = {k: [] for k in k_values}
        recall_at: dict[int, list[float]] = {k: [] for k in k_values}
        reciprocal_ranks: list[float] = []
        ndcg_scores: list[float] = []
        latencies: list[float] = []

        for item in unique_queries:
            start = time.time()
            result = await self._retrieve.retrieve(
                RetrievalQuery(
                    query_text=item["query"], user_id=user_id, top_k=max_k,
                )
            )
            latencies.append((time.time() - start) * 1000)

            retrieved_ids = [c.memory.memory_id for c in result.candidates]
            relevant_ids = group_to_ids.get(item.get("group_id", ""), set())

            # Metrics at each k.
            for k in k_values:
                top_k_ids = set(retrieved_ids[:k])
                relevant_in_k = len(top_k_ids & relevant_ids)
                precision_at[k].append(relevant_in_k / k)
                recall_at[k].append(
                    relevant_in_k / len(relevant_ids) if relevant_ids else 0.0
                )

            # MRR.
            rr = 0.0
            for rank_idx, c in enumerate(result.candidates):
                if c.memory.memory_id in relevant_ids:
                    rr = 1.0 / (rank_idx + 1)
                    break
            reciprocal_ranks.append(rr)

            # nDCG@5.
            relevances = [
                1 if c.memory.memory_id in relevant_ids else 0
                for c in result.candidates[:5]
            ]
            ndcg_scores.append(
                _compute_ndcg(relevances, len(relevant_ids), 5)
            )

        def _avg(lst: list[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        def _f1(p: float, r: float) -> float:
            return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

        p1 = _avg(precision_at.get(1, []))
        p3 = _avg(precision_at.get(3, []))
        p5 = _avg(precision_at.get(5, []))
        r1 = _avg(recall_at.get(1, []))
        r3 = _avg(recall_at.get(3, []))
        r5 = _avg(recall_at.get(5, []))

        metrics = RetrievalMetrics(
            precision_at_1=p1, precision_at_3=p3, precision_at_5=p5,
            recall_at_1=r1, recall_at_3=r3, recall_at_5=r5,
            f1_at_1=_f1(p1, r1), f1_at_3=_f1(p3, r3), f1_at_5=_f1(p5, r5),
            mrr=_avg(reciprocal_ranks),
            ndcg_at_5=_avg(ndcg_scores),
            latency_ms=_avg(latencies),
            total_queries=len(unique_queries),
            total_memories=len(dataset) + len(noise_facts),
        )

        logger.info(
            f"Retrieval eval ({mode.value}): P@1={p1:.3f}, P@3={p3:.3f}, P@5={p5:.3f}, "
            f"R@5={r5:.3f}, MRR={metrics.mrr:.3f}, nDCG@5={metrics.ndcg_at_5:.3f}"
        )
        return metrics

    async def run_contradiction_eval(
        self, user_id: str = "eval_contradiction_user",
    ) -> ContradictionMetrics:
        """Evaluate contradiction detection accuracy."""
        dataset = self._dataset.get_contradiction_dataset()
        logger.info(f"Running contradiction eval on {len(dataset)} pairs")

        tp = fp = fn = tn = 0
        for item in dataset:
            mem_a = await self._ingest.ingest_text(
                text=item["memory_a"], user_id=user_id,
            )
            mem_b = await self._ingest.ingest_text(
                text=item["memory_b"], user_id=user_id,
            )
            report = await self._contradiction.check_contradiction(mem_a, mem_b)
            detected = report is not None

            if item["is_contradiction"] and detected:
                tp += 1
            elif not item["is_contradiction"] and not detected:
                tn += 1
            elif not item["is_contradiction"] and detected:
                fp += 1
            else:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics = ContradictionMetrics(
            true_positives=tp, true_negatives=tn,
            false_positives=fp, false_negatives=fn,
            precision=precision, recall=recall, f1=f1,
            total_pairs=len(dataset),
        )
        logger.info(f"Contradiction eval: P={precision:.3f}, R={recall:.3f}, F1={f1:.3f}")
        return metrics

    async def run_full_eval(
        self,
        user_id_prefix: str = "eval",
        mode: EvalMode = EvalMode.EXPANDED,
    ) -> EvaluationReport:
        """Run all evaluation suites and return a comprehensive report."""
        report = EvaluationReport(eval_name="full_eval", eval_mode=mode.value)
        logger.info(f"Starting full evaluation suite ({mode.value})")

        report.retrieval = await self.run_retrieval_eval(
            user_id=f"{user_id_prefix}_retrieval", mode=mode,
        )

        if mode != EvalMode.CONTRADICTION:
            report.contradiction = await self.run_contradiction_eval(
                user_id=f"{user_id_prefix}_contradiction",
            )

        report.completed_at = datetime.now(timezone.utc)
        logger.info(f"Full eval complete. Run ID: {report.run_id}")
        return report
