"""Agent state: shared Pydantic model passed between all graph nodes."""

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from agent.request_plan import RequestPlan
from agent.schemas import DocumentQueryPlan, FinalAnswer

SourceMode = Literal["none", "selected", "all"]


class UserQuery(BaseModel):
    raw_text: str
    formula: str | None = None


class ContextProfile(BaseModel):
    improve: list[str] = Field(default_factory=list)
    preserve: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal["bigquery", "pdf", "table", "figure", "paper", "internal_report"]
    summary: str
    citation: str
    confidence: Literal["high", "medium", "low"]
    limitations: list[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    claim: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


class DocumentQueryRewrite(BaseModel):
    rewritten_query: str
    alternative_queries: list[str] = Field(default_factory=list)
    rewrite_notes: list[str] = Field(default_factory=list)


class AgentState(BaseModel):
    """Shared state passed between agent graph nodes.

    Nodes update state immutably via ``state.model_copy(update={...})``.
    Never mutate fields in place.
    """

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    query: UserQuery
    include_debug_trace: bool = False
    request_plan: RequestPlan | None = None
    target_profile: ContextProfile | None = None
    bigquery_results: list[dict] = Field(default_factory=list)
    database_evidence: dict = Field(default_factory=dict)
    document_scopes: list[Literal["internal", "external"]] = Field(default_factory=list)
    document_query_plan: DocumentQueryPlan | None = None
    document_query_rewrite: DocumentQueryRewrite | None = None
    document_evidence: dict = Field(default_factory=dict)
    source_mode: SourceMode = "all"
    selected_document_ids: list[str] = Field(default_factory=list)
    resolved_document_targets: list[dict[str, Any]] = Field(default_factory=list)
    source_filters: dict[str, Any] = Field(default_factory=dict)
    retrieval_queries: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    reranked_evidence: list[EvidenceItem] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    citation_errors: list[str] = Field(default_factory=list)
    supervisor_meta: dict = Field(default_factory=dict)
    evidence_packet: dict | None = None
    synthesis_retry_count: int = Field(default=0, ge=0, le=1)
    final_answer: FinalAnswer | None = None
