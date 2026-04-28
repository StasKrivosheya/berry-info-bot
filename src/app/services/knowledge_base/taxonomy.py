from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.knowledge_base.normalizer import normalize_cell_text

DEFAULT_TAXONOMY_PATH = Path("data/knowledge_base/taxonomy.toml")
GENERAL_TOPIC_ID = "general"


@dataclass(frozen=True, slots=True)
class DirectionDefinition:
    id: str
    label_uk: str
    short_label: str
    aliases: tuple[str, ...]
    source_categories: tuple[str, ...]
    active: bool = True


@dataclass(frozen=True, slots=True)
class TopicDefinition:
    id: str
    label_uk: str
    aliases: tuple[str, ...]
    direction_sensitive: bool = False
    default_direction_id: str | None = None


@dataclass(frozen=True, slots=True)
class SourceMapping:
    source_file: str | None
    sheet_name: str | None
    source_category: str | None
    logical_id: str | None
    direction_id: str | None
    topic_ids: tuple[str, ...]
    period_label: str | None


@dataclass(frozen=True, slots=True)
class TaxonomyMatch:
    direction_id: str | None
    topic_ids: tuple[str, ...]
    period_label: str | None = None


class KnowledgeBaseTaxonomy:
    """Controlled business vocabulary shared by routing, ingest, and retrieval."""

    def __init__(
        self,
        *,
        directions: tuple[DirectionDefinition, ...],
        topics: tuple[TopicDefinition, ...],
        sources: tuple[SourceMapping, ...] = (),
    ) -> None:
        self.directions = {direction.id: direction for direction in directions}
        self.topics = {topic.id: topic for topic in topics}
        self.sources = sources

    @property
    def active_directions(self) -> tuple[DirectionDefinition, ...]:
        return tuple(direction for direction in self.directions.values() if direction.active)

    def normalize_direction_id(self, value: str | None) -> str | None:
        normalized = _normalize_key(value)
        if not normalized:
            return None
        if normalized in self.directions:
            return normalized
        for direction in self.directions.values():
            if normalized in {_normalize_key(alias) for alias in direction.aliases}:
                return direction.id
        return None

    def normalize_topic_id(self, value: str | None) -> str | None:
        normalized = _normalize_key(value)
        if not normalized:
            return None
        if normalized in self.topics:
            return normalized
        for topic in self.topics.values():
            if normalized in {_normalize_key(alias) for alias in topic.aliases}:
                return topic.id
        return None

    def infer_direction_id_from_text(self, text: str) -> str | None:
        haystack = _normalize_text(text)
        if not haystack:
            return None
        matches: list[tuple[int, str]] = []
        for direction in self.directions.values():
            aliases = (direction.id, direction.short_label, direction.label_uk, *direction.aliases)
            for alias in aliases:
                normalized_alias = _normalize_text(alias)
                if normalized_alias and normalized_alias in haystack:
                    matches.append((len(normalized_alias), direction.id))
                    break
        if not matches:
            return None
        matches.sort(reverse=True)
        return matches[0][1]

    def infer_topic_ids_from_text(self, text: str) -> tuple[str, ...]:
        haystack = _normalize_text(text)
        if not haystack:
            return ()
        matches: list[tuple[int, str]] = []
        for topic in self.topics.values():
            aliases = (topic.id, topic.label_uk, *topic.aliases)
            for alias in aliases:
                normalized_alias = _normalize_text(alias)
                if normalized_alias and normalized_alias in haystack:
                    matches.append((len(normalized_alias), topic.id))
                    break
        matches.sort(reverse=True)
        ordered_ids: list[str] = []
        for _, topic_id in matches:
            if topic_id not in ordered_ids:
                ordered_ids.append(topic_id)
        if len(ordered_ids) > 1 and GENERAL_TOPIC_ID in ordered_ids:
            ordered_ids.remove(GENERAL_TOPIC_ID)
        return tuple(ordered_ids)

    def match_source(
        self,
        *,
        source_file: str,
        sheet_name: str | None,
        source_category: str,
        logical_id: str,
    ) -> TaxonomyMatch:
        for mapping in self.sources:
            if _source_mapping_matches(
                mapping,
                source_file=source_file,
                sheet_name=sheet_name,
                source_category=source_category,
                logical_id=logical_id,
            ):
                return TaxonomyMatch(
                    direction_id=self.normalize_direction_id(mapping.direction_id),
                    topic_ids=self.normalize_topic_ids(mapping.topic_ids),
                    period_label=mapping.period_label,
                )

        direction_id = self._direction_for_source_category(source_category)
        topic_ids = self.infer_topic_ids_from_text(" ".join((source_category, logical_id)))
        return TaxonomyMatch(
            direction_id=direction_id,
            topic_ids=topic_ids,
            period_label=None,
        )

    def normalize_topic_ids(self, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            topic_id = self.normalize_topic_id(value)
            if topic_id is not None and topic_id not in normalized:
                normalized.append(topic_id)
        return tuple(normalized)

    def should_clarify_direction(
        self,
        *,
        topic_id: str | None,
        direction_id: str | None,
    ) -> bool:
        if direction_id is not None or topic_id is None:
            return False
        topic = self.topics.get(topic_id)
        return bool(topic and topic.direction_sensitive and len(self.active_directions) > 1)

    def build_direction_clarification_text(self, topic_id: str | None) -> str:
        topic = self.topics.get(topic_id or "")
        topic_prefix = ""
        if topic is not None:
            topic_prefix = f" для теми «{topic.label_uk}»"
        direction_labels = ", ".join(
            f"{direction.short_label} — {direction.label_uk}"
            for direction in self.active_directions
        )
        return (
            f"Щоб не переплутати інформацію{topic_prefix}, уточніть напрямок: "
            f"{direction_labels}."
        )

    def build_router_prompt_section(self) -> str:
        direction_lines = [
            (
                f"- {direction.id}: {direction.label_uk}; aliases: "
                f"{', '.join(direction.aliases[:6])}"
            )
            for direction in self.active_directions
        ]
        topic_lines = [
            (
                f"- {topic.id}: {topic.label_uk}; "
                f"direction_sensitive={str(topic.direction_sensitive).lower()}; "
                f"aliases: {', '.join(topic.aliases[:8])}"
            )
            for topic in self.topics.values()
            if topic.id != GENERAL_TOPIC_ID
        ]
        return "\n".join(
            (
                "Controlled vocabulary:",
                "Directions:",
                *direction_lines,
                "Topics:",
                *topic_lines,
            )
        )

    def _direction_for_source_category(self, source_category: str) -> str | None:
        source_category_key = _normalize_text(source_category)
        for direction in self.directions.values():
            for configured_category in direction.source_categories:
                if _normalize_text(configured_category) == source_category_key:
                    return direction.id
        return None


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> KnowledgeBaseTaxonomy:
    if not path.exists():
        return KnowledgeBaseTaxonomy(directions=(), topics=())

    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    directions = tuple(
        DirectionDefinition(
            id=str(direction_id).strip(),
            label_uk=_required_str(raw_direction, "label_uk"),
            short_label=str(raw_direction.get("short_label", direction_id)).strip(),
            aliases=_str_tuple(raw_direction.get("aliases")),
            source_categories=_str_tuple(raw_direction.get("source_categories")),
            active=bool(raw_direction.get("active", True)),
        )
        for direction_id, raw_direction in _dict(payload.get("directions")).items()
    )
    topics = tuple(
        TopicDefinition(
            id=str(topic_id).strip(),
            label_uk=_required_str(raw_topic, "label_uk"),
            aliases=_str_tuple(raw_topic.get("aliases")),
            direction_sensitive=bool(raw_topic.get("direction_sensitive", False)),
            default_direction_id=_optional_str(raw_topic.get("default_direction_id")),
        )
        for topic_id, raw_topic in _dict(payload.get("topics")).items()
    )
    sources = tuple(
        _parse_source_mapping(raw_source) for raw_source in _list(payload.get("sources"))
    )
    return KnowledgeBaseTaxonomy(directions=directions, topics=topics, sources=sources)


@lru_cache(maxsize=4)
def get_default_taxonomy() -> KnowledgeBaseTaxonomy:
    return load_taxonomy(DEFAULT_TAXONOMY_PATH)


def _parse_source_mapping(raw_source: object) -> SourceMapping:
    data = _dict(raw_source)
    return SourceMapping(
        source_file=_optional_str(data.get("source_file")),
        sheet_name=_optional_str(data.get("sheet_name")),
        source_category=_optional_str(data.get("source_category")),
        logical_id=_optional_str(data.get("logical_id")),
        direction_id=_optional_str(data.get("direction_id")),
        topic_ids=_str_tuple(data.get("topic_ids")),
        period_label=_optional_str(data.get("period_label")),
    )


def _source_mapping_matches(
    mapping: SourceMapping,
    *,
    source_file: str,
    sheet_name: str | None,
    source_category: str,
    logical_id: str,
) -> bool:
    checks = (
        (mapping.source_file, source_file),
        (mapping.sheet_name, sheet_name),
        (mapping.source_category, source_category),
        (mapping.logical_id, logical_id),
    )
    for expected, actual in checks:
        if expected is None:
            continue
        if _normalize_text(expected) != _normalize_text(actual or ""):
            return False
    return any(expected is not None for expected, _ in checks)


def _required_str(raw_value: object, key: str) -> str:
    value = _optional_str(_dict(raw_value).get(key))
    if value is None:
        msg = f"Taxonomy item must include '{key}'."
        raise ValueError(msg)
    return value


def _optional_str(raw_value: object) -> str | None:
    if raw_value is None:
        return None
    normalized = normalize_cell_text(str(raw_value))
    return normalized or None


def _str_tuple(raw_value: object) -> tuple[str, ...]:
    if not isinstance(raw_value, list):
        return ()
    values: list[str] = []
    for item in raw_value:
        normalized = _optional_str(item)
        if normalized and normalized not in values:
            values.append(normalized)
    return tuple(values)


def _dict(raw_value: object) -> dict[str, object]:
    if isinstance(raw_value, dict):
        return raw_value
    return {}


def _list(raw_value: object) -> list[object]:
    if isinstance(raw_value, list):
        return raw_value
    return []


def _normalize_key(value: str | None) -> str:
    return normalize_cell_text(str(value or "")).casefold().replace("-", "_").replace(" ", "_")


def _normalize_text(value: str) -> str:
    return normalize_cell_text(value).casefold()
