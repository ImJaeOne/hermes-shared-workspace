"""Research engine adapters for the AX planning material worker.

The production workflow must not depend on Google NotebookLM Enterprise APIs.
This module keeps the engine boundary explicit so local/CI can use a deterministic
mock adapter while deployed environments may opt into the unofficial
``notebooklm-py`` web adapter with a graceful fallback.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .artifact_storage import get_artifact_storage
except ImportError:
    from artifact_storage import get_artifact_storage

DEFAULT_RESEARCH_ENGINE = "mock"
DEFAULT_RESEARCH_FALLBACK_ENGINE = "mock"
DEFAULT_RESEARCH_SKILL_ID = "skill_001"
SAFE_ENGINE_UNAVAILABLE_MESSAGE = "자료조사 엔진 연결 문제로 담당자 확인이 필요합니다. 대체 분석으로 초안을 생성할 수 있습니다."
SAFE_ENGINE_FAILED_MESSAGE = "자료조사 실행 중 일시적인 문제가 발생했습니다. 담당자가 확인 후 다시 안내드리겠습니다."


def normalize_engine_name(value: str | None, *, default: str = DEFAULT_RESEARCH_ENGINE) -> str:
    """Normalize env/config names such as ``notebooklm-py`` to stable keys."""
    engine = (value or default or DEFAULT_RESEARCH_ENGINE).strip().lower().replace("-", "_")
    return engine or default


def configured_research_engine() -> str:
    return normalize_engine_name(os.getenv("HERMES_AX_RESEARCH_ENGINE"), default=DEFAULT_RESEARCH_ENGINE)


def configured_fallback_engine() -> str:
    return normalize_engine_name(
        os.getenv("HERMES_AX_RESEARCH_FALLBACK_ENGINE"),
        default=DEFAULT_RESEARCH_FALLBACK_ENGINE,
    )


@dataclass(frozen=True)
class ResearchAdapterResult:
    """Normalized result returned by any research adapter."""

    engine: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ResearchAdapterFailure(Exception):
    """Base exception that separates safe user copy from internal diagnostics."""

    def __init__(
        self,
        code: str,
        *,
        safe_message: str = SAFE_ENGINE_FAILED_MESSAGE,
        diagnostics: dict[str, Any] | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.safe_message = safe_message
        self.diagnostics = diagnostics or {}


class ResearchAdapterUnavailable(ResearchAdapterFailure):
    """Raised when an optional adapter cannot run in the current environment."""

    def __init__(self, code: str, *, diagnostics: dict[str, Any] | None = None):
        super().__init__(code, safe_message=SAFE_ENGINE_UNAVAILABLE_MESSAGE, diagnostics=diagnostics)


class ResearchAdapter:
    engine = "base"

    def run(self, payload: dict[str, Any], prompt: dict[str, Any]) -> ResearchAdapterResult:  # pragma: no cover - interface
        raise NotImplementedError


def _company_name(payload: dict[str, Any]) -> str:
    return str(payload.get("company_name") or "회사").strip() or "회사"


def _task_label(payload: dict[str, Any]) -> str:
    return "수정 자료조사" if payload.get("task_type") == "revision" else "자료조사"


def _looks_like_generated_artifact_name(value: str, artifact: dict[str, Any]) -> bool:
    """Detect storage-generated artifact names such as ``art_*.pdf``."""
    name = Path(value or "").name.strip()
    if not name:
        return False
    stem = Path(name).stem
    artifact_id = str(artifact.get("id") or "").strip()
    if stem.startswith("art_"):
        return True
    return bool(artifact_id and (stem == artifact_id or name.startswith(f"{artifact_id}.")))


def _source_title(source: dict[str, Any], index: int) -> str:
    artifact = source.get("artifact") if isinstance(source.get("artifact"), dict) else {}
    artifact_original = str(artifact.get("original_filename") or "").strip()
    candidates = [
        str(source.get("title") or "").strip(),
        str(source.get("filename") or "").strip(),
        str(source.get("original_filename") or "").strip(),
        artifact_original,
        str(artifact.get("title") or "").strip(),
        str(source.get("slack_file_id") or "").strip(),
        f"자료 {index + 1}",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if artifact_original and candidate != artifact_original and _looks_like_generated_artifact_name(candidate, artifact):
            continue
        return candidate
    return f"자료 {index + 1}"


def _resolve_local_artifact_path(artifact: dict[str, Any]) -> str:
    """Resolve local artifact storage keys without allowing path traversal."""
    storage_backend = str(artifact.get("storage_backend") or "local").strip() or "local"
    if storage_backend != "local":
        return ""

    storage = get_artifact_storage()
    candidates = [
        str(artifact.get("storage_key") or "").strip(),
        str(artifact.get("file_path") or "").strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            resolved = storage.resolve_path(candidate)
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file():
            return str(resolved)
    return ""


def _text_preview(value: str, *, limit: int = 160) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _source_summary_lines(sources: list[dict[str, Any]]) -> list[str]:
    if not sources:
        return ["- 전달 자료 없음: Slack에서 전달된 자료가 없는 상태로 기본 조사 초안을 생성했습니다."]

    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        artifact = source.get("artifact") if isinstance(source.get("artifact"), dict) else {}
        title = _source_title(source, index - 1)
        mime = str(source.get("mimetype") or artifact.get("mime_type") or artifact.get("content_type") or "").strip()
        content = str(artifact.get("content") or "")
        suffix = f" ({mime})" if mime else ""
        preview = _text_preview(content)
        if preview:
            lines.append(f"- {index}. {title}{suffix}: {preview}")
        else:
            lines.append(f"- {index}. {title}{suffix}")
    return lines


class MockResearchAdapter(ResearchAdapter):
    """Deterministic adapter for local development, CI, and safe fallback."""

    engine = "mock"

    def run(self, payload: dict[str, Any], prompt: dict[str, Any]) -> ResearchAdapterResult:
        company = _company_name(payload)
        task_label = _task_label(payload)
        prompt_name = str(prompt.get("name") or "기획 자료조사 결과 정리").strip()
        prompt_skill_id = str(prompt.get("skill_id") or DEFAULT_RESEARCH_SKILL_ID).strip()
        sources = payload.get("source_files") if isinstance(payload.get("source_files"), list) else []
        source_lines = _source_summary_lines(sources)
        revision = payload.get("revision") if isinstance(payload.get("revision"), dict) else {}
        revision_instruction = str(revision.get("instruction") or "").strip()
        base_report = revision.get("base_report") if isinstance(revision.get("base_report"), dict) else {}

        title = f"{company} {'자료조사 수정 결과' if payload.get('task_type') == 'revision' else '자료조사 결과'}"
        content_lines = [
            f"## {title}",
            "",
            "### 핵심 요약",
            f"- {company} 담당자가 Slack에 전달한 자료를 기준으로 {task_label} 초안을 정리했습니다.",
            "- 이 결과는 배포/CI 환경에서도 검증 가능한 기본 자료조사 엔진으로 생성되었습니다.",
            "- 실제 운영에서는 연결된 자료조사 엔진이 사용 가능하면 동일한 산출물 형식으로 결과를 반환합니다.",
            "",
            "### 확인한 자료",
            *source_lines,
            "",
            "### 회사/제품 이해",
            f"- {company}의 소개 자료, 담당자 메모, 첨부 파일명을 기준으로 콘텐츠 기획에 필요한 기본 맥락을 추출했습니다.",
            "- 첨부 자료 원문을 확인할 수 있는 항목은 자료명 중심으로 출처를 남겼습니다.",
            "",
            "### 콘텐츠 기획 포인트",
            "1. 회사가 강조하려는 핵심 역량과 고객에게 보여줄 신뢰 요소를 먼저 배치합니다.",
            "2. 제품/서비스 설명은 담당자가 제공한 자료명을 근거로 간결하게 구조화합니다.",
            "3. 후속 시놉시스, 스토리보드, 원고는 자료조사 확정 뒤 별도 단계에서 다룹니다.",
            "",
            "### 추가 확인 질문",
            "- 외부에 공개해도 되는 수치, 고객사, 인증 정보의 범위를 확인해주세요.",
            "- 대표 이미지나 로고 등 시각 자료 사용 가능 여부를 확인해주세요.",
        ]
        if revision_instruction:
            content_lines.extend(
                [
                    "",
                    "### 수정 요청 반영 메모",
                    f"- 요청 사항: {revision_instruction}",
                    f"- 기준 결과: {base_report.get('title') or '이전 자료조사 결과'}",
                ]
            )

        metadata = {
            "engine": self.engine,
            "task_type": payload.get("task_type") or "initial_research",
            "source_file_count": len(sources),
            "prompt_source": prompt.get("source") or "skills",
            "prompt_skill_id": prompt_skill_id,
            "prompt_name": prompt_name,
        }
        return ResearchAdapterResult(engine=self.engine, title=title, content="\n".join(content_lines), metadata=metadata)


class NotebookLmPyResearchAdapter(ResearchAdapter):
    """Optional NotebookLM web adapter powered by ``notebooklm-py``.

    The adapter is intentionally lazy: importing or configuring ``notebooklm-py``
    is not required for local tests. Missing auth/session/package raises
    ``ResearchAdapterUnavailable`` so the caller can use a non-technical fallback.
    """

    engine = "notebooklm_py"

    def run(self, payload: dict[str, Any], prompt: dict[str, Any]) -> ResearchAdapterResult:
        storage_path, temporary_path = self._resolve_storage_path()
        profile = os.getenv("HERMES_AX_NOTEBOOKLM_PROFILE") or None
        if not storage_path and not profile:
            raise ResearchAdapterUnavailable("notebooklm_auth_not_configured", diagnostics={"missing": "storage_state"})

        try:
            return asyncio.run(self._run_async(payload, prompt, storage_path=storage_path, profile=profile))
        except ResearchAdapterFailure:
            raise
        except ModuleNotFoundError as exc:
            if exc.name == "notebooklm":
                raise ResearchAdapterUnavailable("notebooklm_py_not_installed", diagnostics={"missing_module": exc.name}) from exc
            raise ResearchAdapterFailure("notebooklm_dependency_missing", diagnostics={"missing_module": exc.name}) from exc
        except Exception as exc:  # pragma: no cover - exercised only with live NotebookLM
            raise ResearchAdapterFailure(
                "notebooklm_py_execution_failed",
                safe_message=SAFE_ENGINE_UNAVAILABLE_MESSAGE,
                diagnostics={"exception_type": type(exc).__name__, "message": str(exc)[:500]},
            ) from exc
        finally:
            if temporary_path:
                try:
                    Path(temporary_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def _resolve_storage_path(self) -> tuple[str | None, str | None]:
        explicit_path = (os.getenv("HERMES_AX_NOTEBOOKLM_AUTH_PATH") or "").strip()
        if explicit_path:
            return explicit_path, None

        auth_json = (os.getenv("HERMES_AX_NOTEBOOKLM_AUTH_JSON") or "").strip()
        if not auth_json:
            return None, None

        if auth_json.startswith("{") or auth_json.startswith("["):
            tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
            try:
                tmp.write(auth_json)
                return tmp.name, tmp.name
            finally:
                tmp.close()

        if Path(auth_json).expanduser().exists():
            return str(Path(auth_json).expanduser()), None

        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        try:
            tmp.write(auth_json)
            return tmp.name, tmp.name
        finally:
            tmp.close()

    async def _run_async(
        self,
        payload: dict[str, Any],
        prompt: dict[str, Any],
        *,
        storage_path: str | None,
        profile: str | None,
    ) -> ResearchAdapterResult:
        from notebooklm import NotebookLMClient

        company = _company_name(payload)
        title = f"AX 자료조사 - {company} - {payload.get('workflow_id') or 'workflow'}"
        keep_notebooks = os.getenv("HERMES_AX_NOTEBOOKLM_KEEP_NOTEBOOKS", "false").strip().lower() in {"1", "true", "yes", "on"}
        timeout = float(os.getenv("HERMES_AX_NOTEBOOKLM_TIMEOUT", "60"))
        context_kwargs: dict[str, Any] = {"timeout": timeout}
        if storage_path:
            context_kwargs["path"] = storage_path
        if profile:
            context_kwargs["profile"] = profile

        notebook_id = ""
        async with NotebookLMClient.from_storage(**context_kwargs) as client:
            notebook = await client.notebooks.create(title)
            notebook_id = str(getattr(notebook, "id", ""))
            try:
                source_upload_metadata = await self._add_sources(client, notebook_id, payload)
                answer = await client.chat.ask(notebook_id, self._build_question(payload, prompt))
                content = str(getattr(answer, "answer", "") or answer).strip()
                if not content:
                    raise ResearchAdapterFailure("notebooklm_empty_answer", safe_message=SAFE_ENGINE_FAILED_MESSAGE)
                return ResearchAdapterResult(
                    engine=self.engine,
                    title=f"{company} 자료조사 결과",
                    content=content,
                    metadata={
                        "engine": self.engine,
                        "notebook_id": notebook_id,
                        "source_file_count": len(payload.get("source_files") or []),
                        "source_upload_attempted_count": source_upload_metadata.get("attempted_count", 0),
                        "source_upload_succeeded_count": source_upload_metadata.get("succeeded_count", 0),
                        "source_upload_skipped_count": source_upload_metadata.get("skipped_count", 0),
                        "source_uploads": source_upload_metadata.get("sources", []),
                        "prompt_skill_id": prompt.get("skill_id") or DEFAULT_RESEARCH_SKILL_ID,
                    },
                )
            finally:
                if notebook_id and not keep_notebooks:
                    try:
                        await client.notebooks.delete(notebook_id)
                    except Exception:
                        pass

    async def _add_sources(self, client: Any, notebook_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sources = payload.get("source_files") if isinstance(payload.get("source_files"), list) else []
        upload_sources: list[dict[str, Any]] = []
        if not sources:
            await client.sources.add_text(notebook_id, "AX 자료조사 입력", json.dumps(payload, ensure_ascii=False), wait=True)
            return {"attempted_count": 0, "succeeded_count": 0, "skipped_count": 0, "sources": upload_sources}

        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                upload_sources.append(
                    {
                        "index": index,
                        "status": "skipped",
                        "reason": "invalid_source_payload",
                    }
                )
                continue
            title = _source_title(source, index)
            artifact = source.get("artifact") if isinstance(source.get("artifact"), dict) else {}
            file_path = _resolve_local_artifact_path(artifact)
            mime_type = str(source.get("mimetype") or artifact.get("mime_type") or artifact.get("content_type") or "").strip() or None
            diagnostic = {
                "index": index,
                "title": title,
                "filename": str(source.get("filename") or "").strip(),
                "original_filename": str(source.get("original_filename") or artifact.get("original_filename") or "").strip(),
                "artifact_id": str(source.get("artifact_id") or artifact.get("id") or "").strip(),
                "mime_type": mime_type or "",
            }
            if file_path:
                await client.sources.add_file(notebook_id, file_path, mime_type=mime_type, title=title, wait=True)
                upload_sources.append({**diagnostic, "status": "uploaded", "method": "file"})
                continue

            content = str(artifact.get("content") or "").strip()
            if not content:
                content = json.dumps({k: v for k, v in source.items() if k != "artifact"}, ensure_ascii=False, indent=2)
            await client.sources.add_text(notebook_id, title, content, wait=True)
            upload_sources.append({**diagnostic, "status": "uploaded", "method": "text", "reason": "file_path_unavailable"})

        succeeded_count = sum(1 for item in upload_sources if item.get("status") == "uploaded")
        skipped_count = sum(1 for item in upload_sources if item.get("status") == "skipped")
        return {
            "attempted_count": len(sources),
            "succeeded_count": succeeded_count,
            "skipped_count": skipped_count,
            "sources": upload_sources,
        }

    def _build_question(self, payload: dict[str, Any], prompt: dict[str, Any]) -> str:
        company = _company_name(payload)
        revision = payload.get("revision") if isinstance(payload.get("revision"), dict) else {}
        revision_instruction = str(revision.get("instruction") or "").strip()
        prompt_content = str(prompt.get("content") or "").strip()
        source_names = "\n".join(_source_summary_lines(payload.get("source_files") or []))
        parts = [
            prompt_content,
            "",
            f"회사명: {company}",
            f"작업 유형: {_task_label(payload)}",
            "전달 자료:",
            source_names,
            "",
            "회사 담당자가 Slack에서 검토하기 쉬운 한국어 Markdown 자료조사 결과를 작성해주세요.",
            "확인된 사실과 추정을 구분하고, 추가 확인 질문을 포함해주세요.",
            "시놉시스/스토리보드/원고는 후속 단계 placeholder로만 언급해주세요.",
        ]
        if revision_instruction:
            parts.extend(["", f"수정 요청: {revision_instruction}"])
        return "\n".join(parts).strip()


class GeminiRagResearchAdapter(ResearchAdapter):
    """Placeholder boundary for a later low-cost Gemini/RAG fallback."""

    engine = "gemini_rag"

    def run(self, payload: dict[str, Any], prompt: dict[str, Any]) -> ResearchAdapterResult:
        if not os.getenv("HERMES_AX_GEMINI_API_KEY"):
            raise ResearchAdapterUnavailable("gemini_rag_not_configured", diagnostics={"missing": "HERMES_AX_GEMINI_API_KEY"})
        raise ResearchAdapterUnavailable("gemini_rag_not_implemented")


def build_research_adapter(engine: str | None = None) -> ResearchAdapter:
    name = normalize_engine_name(engine, default=configured_research_engine())
    if name == "mock":
        return MockResearchAdapter()
    if name == "notebooklm_py":
        return NotebookLmPyResearchAdapter()
    if name == "gemini_rag":
        return GeminiRagResearchAdapter()
    raise ResearchAdapterUnavailable("unknown_research_engine", diagnostics={"engine": name})


def run_research_adapter(
    payload: dict[str, Any],
    prompt: dict[str, Any],
    *,
    engine: str | None = None,
    fallback_engine: str | None = None,
) -> ResearchAdapterResult:
    """Run the configured adapter, falling back when the primary cannot run."""
    primary_engine = normalize_engine_name(engine or payload.get("research_engine") or configured_research_engine())
    fallback = normalize_engine_name(
        fallback_engine if fallback_engine is not None else payload.get("fallback_engine") or configured_fallback_engine(),
        default="",
    )

    try:
        return build_research_adapter(primary_engine).run(payload, prompt)
    except ResearchAdapterFailure as primary_error:
        if fallback and fallback != primary_engine:
            fallback_result = build_research_adapter(fallback).run(payload, prompt)
            metadata = dict(fallback_result.metadata)
            metadata.update(
                {
                    "fallback_from": primary_engine,
                    "primary_error_code": primary_error.code,
                    "safe_message": primary_error.safe_message,
                    "diagnostics": primary_error.diagnostics,
                }
            )
            return ResearchAdapterResult(
                engine=fallback_result.engine,
                title=fallback_result.title,
                content=fallback_result.content,
                metadata=metadata,
            )
        raise


__all__ = [
    "DEFAULT_RESEARCH_ENGINE",
    "DEFAULT_RESEARCH_FALLBACK_ENGINE",
    "DEFAULT_RESEARCH_SKILL_ID",
    "ResearchAdapterFailure",
    "ResearchAdapterResult",
    "ResearchAdapterUnavailable",
    "build_research_adapter",
    "configured_fallback_engine",
    "configured_research_engine",
    "normalize_engine_name",
    "run_research_adapter",
]
