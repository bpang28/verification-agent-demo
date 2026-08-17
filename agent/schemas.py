"""
Core data contracts for the decision-support agent.

Defines the evidence packet, LLM output schemas, and verification result
used across the plan → retrieve → synthesize → verify → compose pipeline.

Design principles:
  - Citations are evidence IDs (EV-{S|D}-NNN), never free-form bibliographic text.
  - SynthesisOutput is the LLM-facing schema; FinalAnswer is the stored record.
  - Confidence is ordinal with a required basis; not_assessable requires abstention.
  - The verifier emits proposition-level verdicts; the policy layer determines action.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------


class ConfidenceLabel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_ASSESSABLE = "not_assessable"


class ClaimVerificationStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class ClaimAction(StrEnum):
    ALLOW = "allow"
    INTERVENE = "intervene"


class WorkflowOutcome(StrEnum):
    PASSED = "passed"
    PASSED_AFTER_RETRY = "passed_after_retry"
    RETRY_TRIGGERED = "retry_triggered"
    PARTIAL_AFTER_RETRY = "partial_after_retry"


EVIDENCE_ID_RE = re.compile(r"^EV-[SD]-\d{3,}$")

# ---------------------------------------------------------------------------
# Evidence packet (consumed by the synthesis LLM)
# ---------------------------------------------------------------------------


class EvidenceParcel(BaseModel):
    """One immutable evidence item. Content is extractive — no paraphrased numbers."""

    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    source_type: str
    title: str = ""
    text: str
    citation: str = ""
    limitations: list[str] = Field(default_factory=list)


class EvidencePacket(BaseModel):
    """Complete set of evidence parcels passed to the synthesis step."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.0"
    question: str
    parcels: list[EvidenceParcel] = Field(default_factory=list)
    database_completeness: dict[str, Any] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return len(self.parcels) == 0

    @property
    def evidence_ids(self) -> set[str]:
        return {p.evidence_id for p in self.parcels}


# ---------------------------------------------------------------------------
# Synthesis output (LLM → code boundary)
# ---------------------------------------------------------------------------


class ScopedAbstention(BaseModel):
    cannot_conclude: list[str] = Field(default_factory=list)
    can_still_state: list[str] = Field(default_factory=list)
    would_resolve: list[str] = Field(default_factory=list)


class SynthesisOutput(BaseModel):
    """
    JSON object emitted by the synthesis LLM.

    Answer prose uses inline [EV-X-NNN] citations before the closing period.
    The verifier checks each atomic claim in the answer against the evidence.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[str] = Field(default_factory=list)
    confidence: ConfidenceLabel
    confidence_basis: list[str] = Field(min_length=1)
    contradictions_noted: list[str] = Field(default_factory=list)
    abstention: Optional[ScopedAbstention] = None

    @model_validator(mode="after")
    def _abstention_required_when_not_assessable(self) -> "SynthesisOutput":
        if self.confidence is ConfidenceLabel.NOT_ASSESSABLE and self.abstention is None:
            raise ValueError("abstention is required when confidence is not_assessable")
        return self


# ---------------------------------------------------------------------------
# Verification result (deterministic policy layer)
# ---------------------------------------------------------------------------


class LLMPropositionCheck(BaseModel):
    """One proposition extracted from a claim, with its verification verdict."""

    model_config = ConfigDict(extra="forbid")

    proposition: str
    status: ClaimVerificationStatus
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evidence_ids(self) -> "LLMPropositionCheck":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("proposition evidence_ids must not contain duplicates")
        if self.status in {ClaimVerificationStatus.SUPPORTED, ClaimVerificationStatus.CONTRADICTED} and not self.evidence_ids:
            raise ValueError(f"{self.status.value} propositions require at least one evidence_id")
        return self


class ClaimAssessment(BaseModel):
    """Aggregated verdict for one claim."""

    claim_id: str
    claim_text: str
    status: ClaimVerificationStatus
    evidence_ids: list[str] = Field(default_factory=list)
    propositions: list[LLMPropositionCheck] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Outcome of the verifier node; stored on FinalAnswer."""

    model_config = ConfigDict(extra="ignore")

    status: WorkflowOutcome
    action: ClaimAction
    claims_checked: int = 0
    claims_llm_checked: int = 0
    assessments: list[ClaimAssessment] = Field(default_factory=list)
    retry_used: bool = False
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Final answer (persisted record)
# ---------------------------------------------------------------------------


class DocumentQueryPlan(BaseModel):
    """Typed document retrieval plan derived from database evidence."""

    model_config = ConfigDict(extra="ignore")

    primary_query: str = ""
    scope: str = "both"
    structured_anchors: list[str] = Field(default_factory=list)
    scope_notes: list[str] = Field(default_factory=list)


class FinalAnswer(BaseModel):
    """The complete answer record including synthesis, verification, and summary."""

    model_config = ConfigDict(extra="ignore")

    synthesis: SynthesisOutput
    verification: Optional[VerificationResult] = None
    executive_summary: Optional[SynthesisOutput] = None
    citation_check: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers used by the verifier pipeline
# ---------------------------------------------------------------------------


class ClaimUnit(BaseModel):
    """One atomic sentence extracted from the synthesis answer for verification."""

    claim_id: str
    claim_text: str
    cited_ids: list[str] = Field(default_factory=list)


class VerifierInputClaim(BaseModel):
    """Payload sent to the verifier LLM for one claim."""

    claim_id: str
    claim_text: str
    evidence: list[dict[str, str]] = Field(default_factory=list)


class LLMVerifierResponse(BaseModel):
    """Top-level output schema for the verifier LLM."""

    checks: list[dict[str, Any]]


def extract_claim_units(synthesis: SynthesisOutput) -> list[ClaimUnit]:
    """Split answer prose into one ClaimUnit per sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", synthesis.answer.strip())
    units: list[ClaimUnit] = []
    for i, sentence in enumerate(sentences, start=1):
        sentence = sentence.strip()
        if not sentence:
            continue
        cited = re.findall(r"EV-[SD]-\d{3,}", sentence)
        units.append(ClaimUnit(
            claim_id=f"C-{i:03d}",
            claim_text=sentence,
            cited_ids=cited,
        ))
    return units


def build_llm_check_payload(
    units: list[ClaimUnit],
    packet: EvidencePacket,
) -> list[dict[str, Any]]:
    """Build per-claim payloads for the verifier, including relevant evidence text."""
    parcel_by_id = {p.evidence_id: p for p in packet.parcels}
    payload: list[dict[str, Any]] = []
    for unit in units:
        evidence = [
            {"evidence_id": eid, "text": parcel_by_id[eid].text[:400]}
            for eid in unit.cited_ids
            if eid in parcel_by_id
        ]
        if evidence:
            payload.append({
                "claim_id": unit.claim_id,
                "claim_text": unit.claim_text,
                "evidence": evidence,
            })
    return payload


def validate_citations(synthesis: SynthesisOutput, packet: EvidencePacket) -> dict[str, Any]:
    """Check that all inline citations exist in the evidence packet."""
    inline = set(re.findall(r"EV-[SD]-\d{3,}", synthesis.answer))
    declared = set(synthesis.citations)
    available = packet.evidence_ids
    return {
        "inline_not_declared": sorted(inline - declared),
        "declared_not_inline": sorted(declared - inline),
        "cited_not_in_packet": sorted((inline | declared) - available),
        "valid": not bool((inline - declared) | (declared - inline) | ((inline | declared) - available)),
    }
