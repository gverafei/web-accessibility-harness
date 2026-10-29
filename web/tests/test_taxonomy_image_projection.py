"""Vision transport keeps originals and complete visual correspondence."""
import base64
import hashlib
import io
import math
import unittest
from PIL import Image, ImageDraw
from accessibility_taxonomy.image_projection import image_part
from harness.contracts import ContractError


def encode(image, format='PNG'):
    output = io.BytesIO()
    image.save(output, format=format)
    return output.getvalue()


class RasterProjectionTests(unittest.TestCase):
    def test_accepted_small_image_keeps_exact_bytes_and_cache_identity(self):
        body = encode(Image.new('RGBA', (600, 400), (20, 40, 60, 120)))
        part, projection = image_part(body, 'image/png')
        self.assertIsNone(projection)
        self.assertEqual(base64.b64decode(part['image_url']['url'].split(',', 1)[1]), body)

    def test_oversized_image_keeps_four_corners_and_complete_aspect_ratio(self):
        image = Image.new('RGB', (9000, 4000), 'white')
        draw = ImageDraw.Draw(image)
        for box, color in (((0, 0, 899, 899), 'red'), ((8100, 0, 8999, 899), 'green'),
                           ((0, 3100, 899, 3999), 'blue'), ((8100, 3100, 8999, 3999), 'yellow')):
            draw.rectangle(box, fill=color)
        body = encode(image)
        part, evidence = image_part(body, 'image/png')
        raw = base64.b64decode(part['image_url']['url'].split(',', 1)[1])
        output = Image.open(io.BytesIO(raw))
        self.assertLessEqual(math.ceil(output.width / 32) * math.ceil(output.height / 32), 4096)
        self.assertAlmostEqual(output.width / output.height, image.width / image.height, delta=.003)
        self.assertEqual([output.getpixel(point) for point in ((0, 0), (output.width-1, 0), (0, output.height-1), (output.width-1, output.height-1))],
                         [(255, 0, 0), (0, 128, 0), (0, 0, 255), (255, 255, 0)])
        self.assertEqual(evidence['source_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(evidence['projected_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(evidence['source_dimensions'], [9000, 4000])
        self.assertEqual(image.size, (9000, 4000))

    def test_invalid_bytes_are_not_presented_as_verified_pixels(self):
        with self.assertRaises(ContractError):
            image_part(b'not a raster', 'image/png')
