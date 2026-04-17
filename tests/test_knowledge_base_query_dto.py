from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.knowledge_base.query.dto import (
    AnswerResult,
    EvidenceItem,
    EvidencePacket,
    LexicalHit,
    NormalizedQuery,
    RewriteResult,
    RouterDecision,
    VectorHit,
)
from app.services.knowledge_base.query.dto_adapters import build_evidence_packet

FIXED_TIME = datetime(2026, 4, 17, 12, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("instance", "dto_type"),
    [
        (
            NormalizedQuery(
                raw_text="  Де парк? ",
                user_locale="uk-UA",
                detected_language="uk",
                canonical_uk="де парк?",
                created_at=FIXED_TIME,
            ),
            NormalizedQuery,
        ),
        (
            RouterDecision(
                intent="detail",
                needs_clarification=False,
                clarification_question=None,
                missing_slots=("date",),
                routing_flags={
                    "scope": "park_activities",
                    "scopes": ("park_activities", "general"),
                    "strategy": "detail_retrieval",
                    "needs_retrieval": True,
                    "needs_structure": True,
                    "policy_mode": "fallback",
                    "intent_source": "rules",
                    "scope_source": "rules",
                    "strategy_source": "rules",
                    "retrieval_source": "rules",
                },
            ),
            RouterDecision,
        ),
        (
            RewriteResult(
                canonical_uk="де парк?",
                vector_query_uk="berry land адреса",
                lexical={
                    "keywords": ("berry land", "адреса"),
                    "synonyms": ("локація berry land",),
                    "phrases": ("де парк?", "berry land адреса"),
                },
                filters={
                    "category": "park",
                    "logical_id": "schedule",
                    "language": "uk",
                    "attribute_filters": {"logical_id": "schedule", "language": "uk"},
                },
            ),
            RewriteResult,
        ),
        (
            VectorHit(
                section_id="schedule:grafik-roboty",
                file_id="file_schedule",
                score=0.91,
                text="Парк працює з 10:00 до 19:00.",
                attributes={"logical_id": "schedule", "language": "uk", "featured": True},
            ),
            VectorHit,
        ),
        (
            LexicalHit(
                section_id="schedule:grafik-roboty",
                bm25=8.4,
                heading_path=("Графік роботи", "Весна"),
                content="Графік роботи навесні.",
            ),
            LexicalHit,
        ),
        (
            EvidenceItem(
                section_id="schedule:grafik-roboty",
                source_type="vector",
                title="Графік роботи",
                content="Парк працює з 10:00 до 19:00.",
                score=0.91,
            ),
            EvidenceItem,
        ),
        (
            EvidencePacket(
                items=(
                    EvidenceItem(
                        section_id="schedule:grafik-roboty",
                        source_type="vector",
                        title="Графік роботи",
                        content="Парк працює з 10:00 до 19:00.",
                        score=0.91,
                    ),
                ),
                token_budget_used=6,
                truncation_applied=False,
            ),
            EvidencePacket,
        ),
        (
            AnswerResult(
                state="answered",
                answer_text="Парк працює з 10:00 до 19:00.",
                clarification_question=None,
                source_section_ids=("schedule:grafik-roboty",),
                debug_reason="used_hit_anchored_section",
            ),
            AnswerResult,
        ),
    ],
)
def test_dto_json_round_trip(instance, dto_type) -> None:
    payload = instance.to_json()

    restored = dto_type.from_json(payload)

    assert restored == instance


def test_normalized_query_from_json_normalizes_timezone_to_utc() -> None:
    payload = (
        '{"canonical_uk":"де парк?","created_at":"2026-04-17T15:30:00+03:00",'
        '"detected_language":"uk","raw_text":"Де парк?","user_locale":"uk-UA"}'
    )

    restored = NormalizedQuery.from_json(payload)

    assert restored.created_at == FIXED_TIME


def test_build_evidence_packet_marks_truncation_when_budget_is_exceeded() -> None:
    vector_hits = (
        VectorHit(
            section_id="schedule:grafik-roboty",
            file_id="file_schedule",
            score=0.91,
            text="Парк працює з десятої ранку до сьомої вечора щодня.",
            attributes={},
        ),
    )

    packet = build_evidence_packet(
        vector_hits=vector_hits,
        lexical_hits=(),
        token_budget=3,
    )

    assert packet.items == ()
    assert packet.token_budget_used == 0
    assert packet.truncation_applied is True
