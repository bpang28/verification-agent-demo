"""
End-to-end demo: catalysis decision-support agent.

Usage:
    python demo.py                          # runs the default example query
    python demo.py "your question here"     # runs a custom query

Requires: ANTHROPIC_API_KEY set in environment (or .env file).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure supplement root is on the path when run directly.
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic

from agent.state import AgentState, UserQuery
from agent.request_plan import RequestPlan, RequestTask, KnowledgeSource, RequestStatus
from agent.schemas import (
    EvidencePacket, EvidenceParcel, FinalAnswer,
    ClaimAction, VerificationResult, WorkflowOutcome,
)
from infrastructure.mock_database import query as db_query
from infrastructure.mock_retrieval import retrieve

_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
_VERIFIER_MODEL = os.environ.get("VERIFIER_MODEL", "claude-haiku-4-5-20251001")


def _plan_request(client: Anthropic, state: AgentState) -> AgentState:
    """Call Claude to produce a structured request plan."""
    prompt_path = Path(__file__).parent / "agent" / "prompts" / "plan_request.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    response = client.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=system_prompt,
        messages=[{"role": "user", "content": state.query.raw_text}],
    )
    raw = response.content[0].text.strip()
    # Strip optional markdown fences.
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    plan_data = json.loads(raw)
    plan = RequestPlan.model_validate(plan_data)
    print(f"  [plan] status={plan.status}  tasks={[t.value for t in plan.tasks]}")
    print(f"         sources={[s.value for s in plan.knowledge_sources]}")
    if plan.structured_data_question:
        print(f"         db_question='{plan.structured_data_question}'")
    return state.model_copy(update={"request_plan": plan})


def _retrieve_evidence(state: AgentState) -> AgentState:
    """Route to mock database and/or document retrieval based on the plan."""
    plan = state.request_plan
    if plan is None or plan.status != RequestStatus.READY:
        return state

    sources = set(plan.knowledge_sources)
    db_evidence: dict = {}
    doc_evidence: dict = {}

    if KnowledgeSource.STRUCTURED_DATA in sources:
        q = plan.structured_data_question or state.query.raw_text
        print(f"  [db] querying structured data: '{q}'")
        db_evidence = db_query(q)
        n = db_evidence.get("rows_returned", 0)
        print(f"       → {n} rows returned")

    if KnowledgeSource.EXTERNAL_LITERATURE in sources:
        print(f"  [lit] retrieving external literature")
        chunks = retrieve(state.query.raw_text, scope="external", limit=5)
        doc_evidence["external"] = {"chunks": chunks, "source": "external_literature"}
        print(f"       → {len(chunks)} chunks retrieved")

    if KnowledgeSource.INTERNAL_DOCUMENTS in sources:
        print(f"  [lit] retrieving internal documents")
        chunks = retrieve(state.query.raw_text, scope="internal", limit=3)
        doc_evidence["internal"] = {"chunks": chunks, "source": "internal_documents"}
        print(f"       → {len(chunks)} chunks retrieved")

    return state.model_copy(update={
        "database_evidence": db_evidence,
        "document_evidence": doc_evidence,
    })


def _build_evidence_packet(state: AgentState) -> dict:
    """Convert raw retrieval results into the EvidencePacket schema."""
    parcels: list[dict] = []
    ev_counter = {"D": 0, "S": 0}

    def _next_id(prefix: str) -> str:
        ev_counter[prefix] += 1
        return f"EV-{prefix}-{ev_counter[prefix]:03d}"

    # Database rows → EV-S-NNN parcels.
    db = state.database_evidence
    if db.get("evidence_rows"):
        for row in db["evidence_rows"][:15]:
            eid = _next_id("S")
            summary_parts = []
            for k, v in row.items():
                if v is not None:
                    summary_parts.append(f"{k}={v}")
            parcels.append({
                "evidence_id": eid,
                "source_type": "structured",
                "title": f"Database record: {row.get('catalyst_id', 'unknown')}",
                "text": "; ".join(summary_parts),
                "citation": f"Catalyst database, record {row.get('catalyst_id', '?')}",
                "limitations": db.get("limitations", []),
            })

    # Document chunks → EV-D-NNN parcels.
    for scope_data in state.document_evidence.values():
        for chunk in scope_data.get("chunks", [])[:8]:
            eid = _next_id("D")
            parcels.append({
                "evidence_id": eid,
                "source_type": "document",
                "title": chunk.get("title", ""),
                "text": chunk.get("text", ""),
                "citation": chunk.get("citation", ""),
                "limitations": [],
            })

    return {
        "schema_version": "1.0",
        "question": state.query.raw_text,
        "parcels": parcels,
        "database_completeness": db.get("database_completeness", {}),
    }


def _synthesize(client: Anthropic, state: AgentState) -> AgentState:
    """Call Claude to synthesize a cited answer from the evidence packet."""
    prompt_path = Path(__file__).parent / "agent" / "prompts" / "synthesize_answer.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    packet = _build_evidence_packet(state)
    if not packet["parcels"]:
        from agent.schemas import SynthesisOutput, ConfidenceLabel, ScopedAbstention
        synthesis = SynthesisOutput(
            answer="No evidence was retrieved for this query.",
            citations=[],
            confidence=ConfidenceLabel.NOT_ASSESSABLE,
            confidence_basis=["No retrieval results."],
            contradictions_noted=[],
            abstention=ScopedAbstention(cannot_conclude=["Any factual claim."]),
        )
        from agent.schemas import FinalAnswer
        fa = FinalAnswer(synthesis=synthesis)
        return state.model_copy(update={"evidence_packet": packet, "final_answer": fa})

    user_message = json.dumps({
        "question": state.query.raw_text,
        "evidence": packet["parcels"],
    })

    response = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    from agent.schemas import SynthesisOutput, FinalAnswer
    synthesis_data = json.loads(raw)
    synthesis = SynthesisOutput.model_validate(synthesis_data)
    fa = FinalAnswer(synthesis=synthesis)
    print(f"  [synth] confidence={synthesis.confidence}  citations={synthesis.citations}")
    return state.model_copy(update={"evidence_packet": packet, "final_answer": fa})


def _verify(client: Anthropic, state: AgentState) -> AgentState:
    """Run the claim-level verifier (simplified demo path)."""
    if state.final_answer is None or state.evidence_packet is None:
        return state

    prompt_path = Path(__file__).parent / "agent" / "prompts" / "verifier_prompt.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")

    synthesis = state.final_answer.synthesis
    parcels = {p["evidence_id"]: p for p in state.evidence_packet.get("parcels", [])}

    # Build a minimal per-claim payload (one claim = full answer for demo).
    payload = [{
        "claim_id": "C-001",
        "claim_text": synthesis.answer[:800],
        "evidence": [
            {"evidence_id": eid, "text": parcels[eid]["text"][:400]}
            for eid in (synthesis.citations or [])
            if eid in parcels
        ],
    }]

    if not any(c["evidence"] for c in payload):
        result = VerificationResult(
            status=WorkflowOutcome.PASSED,
            action=ClaimAction.ALLOW,
            claims_checked=0,
            claims_llm_checked=0,
        )
        return state.model_copy(update={
            "final_answer": state.final_answer.model_copy(update={"verification": result})
        })

    response = client.messages.create(
        model=_VERIFIER_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    try:
        checks = json.loads(raw).get("checks", [])
    except Exception:
        checks = []

    any_blocked = any(
        p.get("status") in ("unsupported", "contradicted")
        for check in checks
        for p in check.get("propositions", [])
    )
    outcome = WorkflowOutcome.PASSED
    action = ClaimAction.ALLOW
    if any_blocked:
        outcome = WorkflowOutcome.RETRY_TRIGGERED if state.synthesis_retry_count == 0 else WorkflowOutcome.PARTIAL_AFTER_RETRY
        action = ClaimAction.INTERVENE

    result = VerificationResult(
        status=outcome,
        action=action,
        claims_checked=1,
        claims_llm_checked=1,
    )
    print(f"  [verify] outcome={outcome.value}  action={action.value}")
    return state.model_copy(update={
        "final_answer": state.final_answer.model_copy(update={"verification": result})
    })


def run(question: str) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")

    client = Anthropic(api_key=api_key)
    state = AgentState(query=UserQuery(raw_text=question))

    print(f"\nQuery: {question}\n")

    print("[1/4] Planning request...")
    state = _plan_request(client, state)

    plan = state.request_plan
    if plan and plan.status != RequestStatus.READY:
        print(f"\nRequest not ready: {plan.status} — {plan.reasons}")
        return

    print("\n[2/4] Retrieving evidence...")
    state = _retrieve_evidence(state)

    print("\n[3/4] Synthesising answer...")
    state = _synthesize(client, state)

    print("\n[4/4] Verifying claims...")
    state = _verify(client, state)

    fa = state.final_answer
    if fa is None:
        print("\nNo answer produced.")
        return

    print("\n" + "=" * 70)
    print("ANSWER")
    print("=" * 70)
    print(fa.synthesis.answer)
    print(f"\nConfidence : {fa.synthesis.confidence}")
    print(f"Citations  : {', '.join(fa.synthesis.citations) or 'none'}")
    if fa.verification:
        print(f"Verification: {fa.verification.status.value}")
    print("=" * 70)


if __name__ == "__main__":
    default_question = (
        "Compare CER-001 and CER-003 on activity and stability, "
        "and use literature to explain the effect of La promotion."
    )
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else default_question
    run(q)
