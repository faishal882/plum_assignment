from io import BytesIO

from PIL import Image, ImageFilter


def degrade_to_unreadable_jpeg(source: bytes) -> bytes:
    """Apply a stable low-resolution blur used only by synthetic fixtures."""
    with Image.open(BytesIO(source)) as image:
        rgb = image.convert("RGB")
        reduced = rgb.resize(
            (max(1, rgb.width // 16), max(1, rgb.height // 16)),
            Image.Resampling.BILINEAR,
        )
        degraded = reduced.resize(rgb.size, Image.Resampling.BILINEAR).filter(
            ImageFilter.GaussianBlur(radius=5)
        )
        output = BytesIO()
        degraded.save(
            output,
            format="JPEG",
            quality=20,
            optimize=False,
            progressive=False,
            subsampling=2,
        )
        return output.getvalue()
