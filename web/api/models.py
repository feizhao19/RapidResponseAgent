from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from geoagent.tools.llm_client import ALLOWED_HF_MODELS

ALLOWED_LLM_MODELS = ALLOWED_HF_MODELS


class ChatTurn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list)
    session_id: str | None = Field(
        default=None,
        description="Server-side session id for persistent multi-turn memory.",
    )
    active_aoi_id: str | None = Field(
        default=None,
        description="UI-selected past assessment AOI; scopes historical answers when set.",
    )
    use_llm: bool = True
    retrieve_only: bool = False
    intent_only: bool = False
    model: str | None = Field(
        default=None,
        description="Hugging Face instruct model id; defaults to Llama 3.2 1B when omitted.",
    )

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if value not in ALLOWED_LLM_MODELS:
            allowed = ", ".join(sorted(ALLOWED_LLM_MODELS))
            raise ValueError(f"Unsupported model {value!r}; choose one of: {allowed}")
        return value


class AskResponse(BaseModel):
    session_id: str | None = None
    intent: str | None = None
    intent_confidence: float | None = None
    intent_method: str | None = None
    intent_rationale: str | None = None
    clarification: str | None = None
    answer_markdown: str | None = None
    tools_called: list[str] = Field(default_factory=list)
    artifacts_used: list[str] = Field(default_factory=list)
    steps_run: list[str] = Field(default_factory=list)
    active_aoi_id: str | None = None
    episode_id: str | None = None
    historical: dict[str, Any] | None = None
    weather: dict[str, Any] | None = None
    pipeline: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=200)
    session_id: str | None = Field(
        default=None,
        description="Optional client-provided session id (UUID).",
    )


class SessionMessage(BaseModel):
    id: str
    role: str
    content: str
    meta: str | None = None
    created_at: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    title: str
    active_aoi_id: str | None = None
    created_at: str
    updated_at: str
    messages: list[SessionMessage] = Field(default_factory=list)


class AssessmentJobResponse(BaseModel):
    job_id: str
    aoi_id: str | None = None
    session_id: str | None = None
    status: str
    message: str | None = None
    job_kind: str | None = None
    vlm_mode: str | None = None
    vlm_limit: int | None = None
    vlm_damaged_only: bool | None = None
    auto_match_pre: bool | None = None
    pre_match: dict[str, Any] | None = None
    valid_pair_coverage: float | None = None
    completed_steps: list[str] = Field(default_factory=list)
    progress: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    aligned_dir: str | None = None
    queue_position: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class VlmReviewRequest(BaseModel):
    mode: str = Field(
        default="both",
        description="both | discrepancy (footprint) | damage",
    )
    limit: int = Field(
        default=2,
        ge=0,
        le=500,
        description="Max candidates to review. Use 0 to review all matching candidates.",
    )
    damaged_only: bool = Field(
        default=True,
        description=(
            "For footprint review: only discrepancies with damage_label outside "
            "no_damage / no_damage_inferred."
        ),
    )
    session_id: str | None = None

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = (value or "both").strip().casefold()
        if normalized not in {"both", "discrepancy", "damage"}:
            raise ValueError("mode must be both, discrepancy, or damage")
        return normalized


class VlmPreferenceRequest(BaseModel):
    review_type: str = Field(description="discrepancy | damage")
    feature_id: str = Field(min_length=1)
    decision: str = Field(description="agree | disagree with the default VLM answer")
    session_id: str | None = None

    @field_validator("review_type")
    @classmethod
    def validate_review_type(cls, value: str) -> str:
        normalized = (value or "").strip().casefold()
        if normalized not in {"discrepancy", "damage"}:
            raise ValueError("review_type must be discrepancy or damage")
        return normalized

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str) -> str:
        normalized = (value or "").strip().casefold()
        if normalized not in {"agree", "disagree"}:
            raise ValueError("decision must be agree or disagree")
        return normalized
