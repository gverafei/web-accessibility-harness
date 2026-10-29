"""Keep verified originals and bound oversized raster evidence for vision judges."""
import base64
import hashlib
import io
import math
from PIL import Image, ImageOps, UnidentifiedImageError
from harness.contracts import ContractError

VERSION = 'verified-raster-projection-v1'
MAX_NATIVE_PATCHES = 30000
PROJECTED_LONG_EDGE = 2048


def image_part(body, mime):
    """Retain accepted images byte-for-byte; never crop an oversized original."""
    try:
        image = Image.open(io.BytesIO(body))
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ContractError('Verified raster evidence cannot be decoded') from error
    with image:
        original_size = image.size
        patches = math.ceil(image.width / 32) * math.ceil(image.height / 32)
        projection = None
        if patches > MAX_NATIVE_PATCHES:
            projected = ImageOps.exif_transpose(image)
            projected.thumbnail((PROJECTED_LONG_EDGE, PROJECTED_LONG_EDGE), Image.Resampling.LANCZOS)
            if projected.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
                projected = projected.convert('RGBA' if 'A' in projected.getbands() else 'RGB')
            output = io.BytesIO()
            projected.save(output, format='PNG')
            projected_body = output.getvalue()
            projection = {
                'version': VERSION,
                'source_sha256': hashlib.sha256(body).hexdigest(),
                'source_dimensions': list(original_size),
                'source_mime': mime,
                'projected_sha256': hashlib.sha256(projected_body).hexdigest(),
                'projected_dimensions': list(projected.size),
                'projected_mime': 'image/png',
                'policy': 'Complete image, aspect ratio preserved, no crop or upscaling; original verified bytes retained.',
            }
            body, mime = projected_body, 'image/png'
    part = {'type': 'image_url', 'image_url': {
        'url': 'data:' + mime + ';base64,' + base64.b64encode(body).decode()}}
    return part, projection
