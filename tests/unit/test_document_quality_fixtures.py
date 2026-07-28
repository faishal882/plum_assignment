from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageDraw

from claims_backend.infrastructure.fixtures.document_quality import (
    degrade_to_unreadable_jpeg,
)


def test_unreadable_transform_is_deterministic_and_produces_valid_jpeg() -> None:
    source = _source_document()

    first = degrade_to_unreadable_jpeg(source)
    second = degrade_to_unreadable_jpeg(source)

    assert first == second
    assert sha256(first).hexdigest() == sha256(second).hexdigest()
    assert first != source
    with Image.open(BytesIO(first)) as transformed:
        assert transformed.format == "JPEG"
        assert transformed.size == (320, 180)


def _source_document() -> bytes:
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 40), "PHARMACY BILL", fill="black")
    draw.text((20, 80), "Total INR 800", fill="black")
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()
