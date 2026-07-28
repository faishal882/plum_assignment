from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
from pypdf import PdfWriter

from claims_backend.application.intelligence import RenderedPageTooLargeError, SourceDocument
from claims_backend.infrastructure.page_renderer import LocalPageRenderer


@pytest.mark.asyncio
async def test_pdf_pages_render_in_stable_order_with_original_provenance(
    tmp_path,
) -> None:
    source = _two_page_pdf()
    relative_path = "objects/source.pdf"
    absolute_path = tmp_path / relative_path
    absolute_path.parent.mkdir(parents=True)
    absolute_path.write_bytes(source)
    document = SourceDocument(
        document_id=UUID("00000000-0000-0000-0000-000000000101"),
        document_version_id=UUID("00000000-0000-0000-0000-000000000201"),
        relative_path=relative_path,
        media_type="application/pdf",
        sha256=sha256(source).hexdigest(),
        page_count=2,
    )
    renderer = LocalPageRenderer(tmp_path, max_page_bytes=5 * 1024 * 1024)

    first = await renderer.render(document)
    replay = await renderer.render(document)

    assert [page.page_number for page in first] == [1, 2]
    assert [page.document_version_id for page in first] == [
        document.document_version_id,
        document.document_version_id,
    ]
    assert all(page.original_sha256 == document.sha256 for page in first)
    assert all(page.media_type == "image/jpeg" for page in first)
    assert all(page.size_bytes <= 5 * 1024 * 1024 for page in first)
    assert [page.sha256 for page in replay] == [page.sha256 for page in first]
    assert [page.content for page in replay] == [page.content for page in first]


@pytest.mark.asyncio
async def test_page_larger_than_provider_limit_is_rejected_explicitly(tmp_path) -> None:
    source = _two_page_pdf()
    relative_path = "objects/source.pdf"
    absolute_path = tmp_path / relative_path
    absolute_path.parent.mkdir(parents=True)
    absolute_path.write_bytes(source)
    renderer = LocalPageRenderer(tmp_path, max_page_bytes=10)

    with pytest.raises(RenderedPageTooLargeError) as captured:
        await renderer.render(
            SourceDocument(
                document_id=UUID("00000000-0000-0000-0000-000000000101"),
                document_version_id=UUID("00000000-0000-0000-0000-000000000201"),
                relative_path=relative_path,
                media_type="application/pdf",
                sha256=sha256(source).hexdigest(),
                page_count=2,
            )
        )

    assert captured.value.page_number == 1
    assert captured.value.max_page_bytes == 10


def _two_page_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.add_blank_page(width=400, height=300)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
