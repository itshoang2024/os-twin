"""Multi-provider LLM wrapper for knowledge extraction, query planning, answer aggregation,
and vision OCR.

Designed for graceful degradation: when no model or API key is configured, every method
returns a sensible empty / fallback value so callers don't have to special-case
the missing-key path.

Uses ``dashboard.llm_wrapper.BaseLLMWrapper`` (shared with MemoryLLM) for the
common plumbing: API-key resolution, client creation, JSON extraction, timeout
handling, and graceful degradation.

Providers are auto-detected from the model name or can be set explicitly via
``provider`` (or ``OSTWIN_KNOWLEDGE_LLM_PROVIDER``).

EPIC-003 Hardening: LLM calls honour OSTWIN_KNOWLEDGE_LLM_TIMEOUT (default 60s).
On timeout, log WARNING and return graceful empty result.

Vision OCR (added for sliding-window PDF extraction):
The :meth:`vision_ocr` method sends a base64-encoded image to the configured
LLM with a data-URI, using ``ChatMessage.images``. Works with all providers
that support multimodal input — OpenAI (gpt-4o), Google/Gemini (including
Vertex AI), and Ollama (llama3.2-vision etc.).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

from dashboard.knowledge.config import LLM_MODEL, LLM_PROVIDER
from dashboard.knowledge.audit import LLM_TIMEOUT  # noqa: WPS433
from dashboard.knowledge.metrics import get_metrics_registry  # noqa: WPS433
from dashboard.llm_client import _detect_provider_from_model
from dashboard.llm_wrapper import BaseLLMWrapper

logger = logging.getLogger(__name__)


_KEY_EXTRACT_SYSTEM = "knowledge.extract_system"
_KEY_EXTRACT_USER = "knowledge.extract_user"
_KEY_PLAN_SYSTEM = "knowledge.plan_system"
_KEY_PLAN_USER = "knowledge.plan_user"
_KEY_AGG_SYSTEM = "knowledge.aggregate_system"
_KEY_AGG_USER = "knowledge.aggregate_user"


def _get_prompt(key: str, lang_code: str, **kwargs) -> str | None:
    try:
        from dashboard.prompts import prompt_service
        return prompt_service.get(key, lang=lang_code, **kwargs)
    except Exception:
        return None


def _format_ontology_profile_hint(ontology_profile_hint: Any | None) -> str:
    """Render an ontology profile hint for extraction prompts."""

    if not ontology_profile_hint:
        return ""
    profile = ontology_profile_hint
    if hasattr(profile, "model_dump"):
        profile = profile.model_dump(mode="json")
    if not isinstance(profile, dict):
        return str(profile)

    concepts = profile.get("concept_types") or {}
    relations = profile.get("relationship_types") or {}
    aliases = profile.get("aliases") or {}
    concept_aliases = profile.get("concept_aliases") or {}

    concept_lines = []
    for cid, item in concepts.items():
        label = item.get("label", cid) if isinstance(item, dict) else cid
        concept_lines.append(f"- {cid}: {label}")
    relation_lines = []
    for rid, item in relations.items():
        if isinstance(item, dict):
            label = item.get("label", rid)
            src = ",".join(item.get("allowed_source_types") or []) or "any"
            tgt = ",".join(item.get("allowed_target_types") or []) or "any"
            relation_lines.append(f"- {rid}: {label} (source: {src}; target: {tgt})")
        else:
            relation_lines.append(f"- {rid}")

    parts = [
        "Ontology profile hint:",
        "Use only these concept type ids when possible:",
        "\n".join(concept_lines) or "- (none)",
        "Use only these relationship type ids when possible:",
        "\n".join(relation_lines) or "- (none)",
    ]
    if aliases:
        parts.append("Relationship aliases: " + ", ".join(f"{k}->{v}" for k, v in aliases.items()))
    if concept_aliases:
        parts.append("Concept aliases: " + ", ".join(f"{k}->{v}" for k, v in concept_aliases.items()))
    parts.append("If no allowed type fits, return your best label; it will be reviewed as a candidate.")
    return "\n".join(parts)


_EXTRACT_SYSTEM = """You are an expert knowledge-graph engineer. Given a chunk of text,
extract the entities and relationships that appear in it. Respond with strict JSON only.

Reply in {language} for entity descriptions and relationship descriptions.

Output schema:
{{
  "entities": [
    {{"name": "<canonical name>", "type": "<category>", "description": "<short description>"}}
  ],
  "relationships": [
    {{"source": "<entity name>", "target": "<entity name>", "relation": "<verb-phrase>", "description": "<short description>"}}
  ]
}}

Rules:
- Only return JSON, no prose, no markdown fences.
- Entity names must match exactly between the entities list and the relationships list.
- Keep descriptions under 200 characters.
- Domain context (if any): {domain}
"""

_EXTRACT_USER = "Extract entities and relationships from the following text:\n\n{text}"


_PLAN_SYSTEM = """You are a query-planning expert. Break a user question down into a small
sequence of sub-queries that can be executed against a knowledge graph + vector store.

Knowledge available (summary):
{knowledge_summary}

Reply in {language}.

Respond with strict JSON: a list of step objects. Each step has:
  - "term": str  — the sub-query text
  - "is_query": bool — True if this step retrieves data, False if it synthesises
  - "category_id": str (optional) — category to scope the retrieval

Cap the plan at {max_steps} steps. Last step should typically be a synthesis (is_query=false).
"""

_PLAN_USER = "User question: {query}\n\nReturn JSON only."


_AGG_SYSTEM = """You are a senior research-assistant. You will be given a list of community-summary
snippets retrieved from a knowledge graph plus the user's question. Synthesise a single,
coherent answer in {language}, citing the snippets where appropriate.

Rules:
- Only use facts that appear in the provided snippets.
- If the snippets don't answer the question, say so.
- Keep the answer focused and under 500 words unless the question asks for detail.
"""

_AGG_USER = (
    "User question: {query}\n\n"
    "Community summaries:\n{summaries}\n\n"
    "Write the final answer."
)


class KnowledgeLLM(BaseLLMWrapper):
    """Multi-provider LLM helper backed by ``dashboard.llm_wrapper``.

    Methods gracefully degrade to empty results when no model or API key is
    configured.  The user must explicitly set a model — there is no hardcoded
    default.

    Provider is auto-detected from the model name (e.g. ``claude-*`` → Anthropic,
    ``gpt-*`` → OpenAI, ``gemini-*`` → Google).  An explicit ``provider``
    parameter overrides the auto-detection.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        # Pre-resolve compatible_url / compatible_key from KnowledgeSettings
        _base_url, _resolved_key = self._resolve_compatible_settings()
        super().__init__(
            model=None,
            provider=None,
            api_key=api_key or _resolved_key,
            timeout=LLM_TIMEOUT,
            base_url=_base_url,
        )
        self._resolve_model_settings(model, provider)

    @staticmethod
    def _resolve_compatible_settings() -> tuple[str | None, str | None]:
        """Resolve openai-compatible URL and key from KnowledgeSettings."""
        try:
            from dashboard.lib.settings.resolver import get_settings_resolver
            resolver = get_settings_resolver()
            master = resolver.get_master_settings()
            if hasattr(master, "knowledge") and master.knowledge:
                know = master.knowledge
                backend = getattr(know, "knowledge_llm_backend", "") or getattr(know, "knowledge_embedding_backend", "")
                if backend == "openai-compatible":
                    url = getattr(know, "knowledge_llm_compatible_url", "") or getattr(know, "knowledge_embedding_compatible_url", "")
                    key = getattr(know, "knowledge_llm_compatible_key", "") or getattr(know, "knowledge_embedding_compatible_key", "")
                    return (url or None, key or None)
        except Exception:
            pass
        return (None, None)

    def _resolve_model_settings(self, model: str | None, provider: str | None) -> None:
        from dashboard.lib.settings.resolver import get_settings_resolver
        try:
            resolver = get_settings_resolver()
            master = resolver.get_master_settings()
            know_cfg = master.knowledge
            master_model = know_cfg.knowledge_llm_model if know_cfg and know_cfg.knowledge_llm_model else ""
            master_provider = know_cfg.knowledge_llm_backend if know_cfg and know_cfg.knowledge_llm_backend else ""
        except Exception:
            master_model = ""
            master_provider = ""

        self.model = model or master_model or LLM_MODEL or ""

        # Knowledge graph extraction/planning must route by the model family so
        # stale dashboard/env provider settings (for example, an Ollama backend)
        # cannot accidentally send a native OpenAI/Gemini/Claude model to the
        # wrong transport. This preserves the citation-refactor contract that
        # `_effective_provider()` is derived from the model identifier whenever
        # a model is explicitly configured.
        if self.model:
            self.provider = _detect_provider_from_model(self.model)
        else:
            self.provider = provider or master_provider or LLM_PROVIDER or None

    def _complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        """Run a single LLM chat call with metrics instrumentation."""
        metrics = get_metrics_registry()
        metrics.counter("llm_calls_total").inc()

        result = super()._complete(system, user, max_tokens=max_tokens)

        if not result:
            metrics.counter("llm_errors_total").inc()
        return result

    def extract_entities(
        self,
        text: str,
        language: str = "English",
        domain: str = "",
        ontology_profile_hint: Any | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Extract entities and relationships from `text`.

        Returns ([entity_dict], [relationship_dict]). When unavailable: ([], []).
        """
        ontology_hint = _format_ontology_profile_hint(ontology_profile_hint)
        effective_domain = domain or "general"
        if ontology_hint:
            effective_domain = f"{effective_domain}\n\n{ontology_hint}"
        system = _get_prompt(
            _KEY_EXTRACT_SYSTEM, language, language=language, domain=effective_domain, ontology_hint=ontology_hint,
        ) or _EXTRACT_SYSTEM.format(language=language, domain=effective_domain)
        user = _get_prompt(
            _KEY_EXTRACT_USER, language, text=text,
        ) or _EXTRACT_USER.format(text=text)
        raw = self._complete(system, user, max_tokens=8192)
        if not raw:
            return [], []
        parsed = self._extract_json(raw)
        if not isinstance(parsed, dict):
            return [], []
        entities = parsed.get("entities", []) or []
        relations = parsed.get("relationships", []) or []
        entities = [e for e in entities if isinstance(e, dict)]
        relations = [r for r in relations if isinstance(r, dict)]
        return entities, relations

    def plan_query(
        self,
        query: str,
        knowledge_summary: str = "",
        max_steps: int = 3,
        language: str = "English",
    ) -> list[dict]:
        """Decompose `query` into a list of step dicts.

        Returns [{term, is_query, category_id?}]. When unavailable, returns a
        single retrieval step with the verbatim query.
        """
        if not self.is_available():
            return [{"term": query, "is_query": True}]
        system = _get_prompt(
            _KEY_PLAN_SYSTEM, language,
            knowledge_summary=knowledge_summary or "(no summary provided)",
            language=language,
            max_steps=max_steps,
        ) or _PLAN_SYSTEM.format(
            knowledge_summary=knowledge_summary or "(no summary provided)",
            language=language,
            max_steps=max_steps,
        )
        user = _get_prompt(
            _KEY_PLAN_USER, language, query=query,
        ) or _PLAN_USER.format(query=query)
        raw = self._complete(system, user, max_tokens=2048)
        if not raw:
            return [{"term": query, "is_query": True}]
        parsed = self._extract_json(raw)
        if not isinstance(parsed, list) or not parsed:
            return [{"term": query, "is_query": True}]
        steps: list[dict] = []
        for step in parsed:
            if not isinstance(step, dict):
                continue
            term = step.get("term")
            if not isinstance(term, str) or not term:
                continue
            normalised = {"term": term, "is_query": bool(step.get("is_query", True))}
            if "category_id" in step and step["category_id"]:
                normalised["category_id"] = str(step["category_id"])
            steps.append(normalised)
        if not steps:
            return [{"term": query, "is_query": True}]
        return steps

    def aggregate_answers(
        self,
        community_summaries: list[str],
        query: str,
        language: str = "English",
    ) -> str:
        """Aggregate per-community answers into a single response.

        When unavailable: returns "\\n\\n".join(community_summaries).
        """
        snippets = [s for s in community_summaries if isinstance(s, str) and s.strip()]
        if not snippets:
            return ""
        system = _get_prompt(
            _KEY_AGG_SYSTEM, language, language=language,
        ) or _AGG_SYSTEM.format(language=language)
        user = _get_prompt(
            _KEY_AGG_USER, language, query=query, summaries="\n---\n".join(snippets),
        ) or _AGG_USER.format(query=query, summaries="\n---\n".join(snippets))
        raw = self._complete(system, user, max_tokens=2048)
        if not raw:
            return "\n\n".join(snippets)
        return raw.strip()

    def vision_ocr(
        self,
        image_data_uri: str,
        prompt: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """Extract text from an image using the configured vision-capable LLM.

        Sends a base64-encoded image (as a data-URI) to the LLM via
        ``ChatMessage.images``. Works with all providers that support
        multimodal input: OpenAI (gpt-4o), Google/Gemini (including
        Vertex AI), and Ollama (llama3.2-vision etc.).

        Parameters
        ----------
        image_data_uri:
            A ``data:image/...;base64,...`` URI containing the image.
        prompt:
            Optional extraction prompt. When None, uses a default
            document OCR prompt that preserves structure and tables.
        max_tokens:
            Maximum tokens for the LLM response.

        Returns
        -------
        str
            Extracted markdown text. Empty string on failure or when
            the LLM is unavailable.
        """
        if not self.is_available():
            return ""

        if not prompt or not prompt.strip():
            prompt = (
                "Extract all text content from this document page image. "
                "Preserve the structure, tables, and formatting as markdown. "
                "Include any headers, footers, and captions."
            )

        from dashboard.llm_client import ChatMessage, run_sync

        client = self._get_client(max_tokens=max_tokens)

        messages = [
            ChatMessage(
                role="system",
                content="You are a document OCR assistant. Extract text from images as structured markdown.",
            ),
            ChatMessage(
                role="user",
                content=prompt,
                images=[image_data_uri],
            ),
        ]

        try:
            result = run_sync(client.chat(messages))
            content = result.content or ""
            metrics = get_metrics_registry()
            metrics.counter("llm_vision_ocr_total").inc()
            return content
        except Exception as exc:
            logger.error(
                "vision_ocr call failed (model=%s, provider=%s): %s",
                self.model,
                self.provider,
                exc,
            )
            metrics = get_metrics_registry()
            metrics.counter("llm_vision_ocr_errors").inc()
            return ""

    def create_vision_client(self) -> Any:
        """Create an LLMClient suitable for vision calls.

        Returns the ``dashboard.llm_client.LLMClient`` instance
        configured with the current model and provider. Callers can
        use this with ``ChatMessage.images`` for custom vision flows.

        Returns None when no model is available.
        """
        if not self.is_available():
            return None
        return self._get_client(max_tokens=4096)
