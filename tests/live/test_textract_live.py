from hashlib import sha256
from io import BytesIO
from os import environ
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from PIL import Image, ImageDraw

from claims_backend.application.intelligence import RenderedPage
from claims_backend.domain.evidence import DocumentRole
from claims_backend.infrastructure.aws.textract import TextractAdapter

pytestmark = [
    pytest.mark.live_aws,
    pytest.mark.skipif(
        environ.get("CLAIMS_RUN_LIVE_AWS") != "1",
        reason="Set CLAIMS_RUN_LIVE_AWS=1 to permit the synthetic AWS smoke test.",
    ),
]


def test_synthetic_page_passes_live_textract_schema_smoke() -> None:
    content = _synthetic_page()
    page = RenderedPage(
        document_id=uuid4(),
        document_version_id=uuid4(),
        page_number=1,
        original_sha256=sha256(content).hexdigest(),
        media_type="image/jpeg",
        content=content,
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        width=640,
        height=320,
        render_version="live-synthetic-v1",
    )
    client = boto3.client(
        "textract",
        region_name=environ.get("CLAIMS_AWS_REGION", "ap-south-1"),
        config=Config(connect_timeout=30, read_timeout=30, retries={"max_attempts": 2}),
    )

    result = TextractAdapter(client).analyze(page, DocumentRole.UNKNOWN)

    assert result.provider_request_id
    assert result.observations
    assert all(item.document_version_id == page.document_version_id for item in result.observations)
    assert all(item.page_number == 1 for item in result.observations)


def _synthetic_page() -> bytes:
    image = Image.new("RGB", (640, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 80), "SYNTHETIC CLAIM DOCUMENT", fill="black")
    draw.text((40, 140), "Patient: TEST PERSON", fill="black")
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()
