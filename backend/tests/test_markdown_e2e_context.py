"""End-to-end proof (Stage 6B, section 25): Markdown/Obsidian ->
`KnowledgeDocument` -> Stage 6A `KnowledgeIndex` -> Stage 6A retrieval ->
`ContextBuilder`, with no additional adapter needed after
`KnowledgeDocument` mapping. Nothing in `app.engine.knowledge` is
modified or reimplemented by this test -- it exercises the real Stage 6A
pipeline directly."""

from pathlib import Path

from app.engine.knowledge.chunking import chunk_document
from app.engine.knowledge.context import ContextBudget, ContextBuilder
from app.engine.knowledge.index import KnowledgeIndex
from app.engine.knowledge.retrieval import KnowledgeSearchRequest, search
from app.integrations.markdown.source import MarkdownKnowledgeSource, MarkdownSourceConfig
from app.integrations.obsidian.adapter import ObsidianVaultAdapter
from app.integrations.obsidian.models import ObsidianVaultConfig


def _write(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _index_all(source: MarkdownKnowledgeSource | ObsidianVaultAdapter) -> KnowledgeIndex:
    index = KnowledgeIndex()
    for document in source.list_documents():
        index.upsert_document(document, chunk_document(document))
    return index


def test_generic_markdown_source_feeds_stage6a_retrieval_and_context_builder(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "architecture.md",
        "# Architecture\n\nKeystone uses a fault-tolerant workflow engine "
        "with circuit breakers and compensation.\n",
    )
    _write(
        tmp_path,
        "api.md",
        "# API\n\nThe REST API exposes workflow execution endpoints.\n",
    )

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="docs"))
    index = _index_all(source)

    results = search(index, KnowledgeSearchRequest(query="workflow engine circuit breaker"))
    assert results
    assert results[0].chunk.source_id == "docs"

    context = ContextBuilder().build(results, ContextBudget(max_chunks=5, max_total_chars=2000))
    assert context.chunks
    assert context.chunks[0].provenance.source_id == "docs"
    assert "circuit breaker" in context.chunks[0].content.lower()


def test_obsidian_adapter_feeds_the_same_pipeline_no_extra_adapter_needed(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "architecture.md",
        "# Architecture\n\nSee [[backend]] for the persistence layer.\n",
    )
    _write(
        tmp_path,
        "backend.md",
        "# Backend\n\nThe backend uses SQLAlchemy for persistence and workflow state.\n",
    )

    adapter = ObsidianVaultAdapter(ObsidianVaultConfig(root=tmp_path, source_id="vault"))
    index = _index_all(adapter)

    results = search(index, KnowledgeSearchRequest(query="persistence workflow state"))
    assert results
    assert all(result.chunk.source_id == "vault" for result in results)

    context = ContextBuilder().build(results)
    assert context.chunks
    assert any("persistence" in chunk.content.lower() for chunk in context.chunks)


def test_context_provenance_traces_back_to_source_document_and_chunk(tmp_path: Path) -> None:
    _write(tmp_path, "notes.md", "# Notes\n\nUnique searchable phrase right here.\n")
    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="docs"))
    index = _index_all(source)

    results = search(index, KnowledgeSearchRequest(query="unique searchable phrase"))
    context = ContextBuilder().build(results)

    assert len(context.chunks) == 1
    provenance = context.chunks[0].provenance
    document = index.get_document(provenance.document_id)
    assert document is not None
    assert document.document_id == "docs::notes.md"
    chunk = index.get_chunk(provenance.chunk_id)
    assert chunk is not None
    assert chunk.content == context.chunks[0].content


def test_multiple_markdown_documents_ranked_by_relevance(tmp_path: Path) -> None:
    _write(tmp_path, "on-topic.md", "# Retrieval\n\nAdaptive retrieval scoring and ranking.\n")
    _write(tmp_path, "off-topic.md", "# Unrelated\n\nA completely different subject entirely.\n")

    source = MarkdownKnowledgeSource(MarkdownSourceConfig(root=tmp_path, source_id="docs"))
    index = _index_all(source)

    results = search(index, KnowledgeSearchRequest(query="adaptive retrieval scoring"))
    assert results
    assert results[0].title == "Retrieval"
