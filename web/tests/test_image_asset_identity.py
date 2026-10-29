"""Image-preservation regressions with static CDN variants and distinct assets."""
import unittest
from harness.html_tools import content_retention


class ImageAssetIdentityTests(unittest.TestCase):
    def measure(self, source, candidate):
        return content_retention(source, candidate, 'https://example.test/', image_asset_equivalence=True)

    def test_size_quality_and_encoding_variants_keep_the_source_image(self):
        source='<img src="/assets/photo.jpg?branch=live&amp;width=3840&amp;quality=75&amp;auto=webp">'
        candidate='<img src="/assets/photo.jpg?branch=live&amp;width=1080&amp;quality=90&amp;auto=avif">'
        result=self.measure(source,candidate)
        self.assertEqual(result['images_percent'],100)
        self.assertEqual(result['image_element_percent'],100)
        self.assertEqual(result['candidate_images'],1)
        self.assertEqual(result['css_image_equivalents'],[])
        self.assertEqual(content_retention(source,candidate,'https://example.test/')['images_percent'],0)

    def test_crop_content_signature_and_filename_changes_remain_distinct(self):
        source='<img src="/photo.jpg?branch=live&amp;crop=1:1&amp;width=3840&amp;sig=abc">'
        for url in ['/photo.jpg?branch=other&crop=1:1&width=1080&sig=abc',
                    '/photo.jpg?branch=live&crop=4:5&width=1080&sig=abc',
                    '/other.jpg?branch=live&crop=1:1&width=1080&sig=abc',
                    '/photo.jpg?branch=live&crop=1:1&width=1080&sig=xyz']:
            with self.subTest(url=url):
                self.assertEqual(self.measure(source,'<img src="'+url+'">')['images_percent'],0)

    def test_unknown_parameters_and_dynamic_endpoints_are_not_discarded(self):
        for old,new in [('/image?id=1&width=3840','/image?id=1&width=1080'),
                        ('/photo.png?auto=art','/photo.png?auto=portrait'),
                        ('/photo.png?width=all','/photo.png?width=10')]:
            with self.subTest(old=old):
                self.assertEqual(self.measure('<img src="'+old+'">','<img src="'+new+'">')['images_percent'],0)

    def test_css_variants_count_without_inventing_image_elements(self):
        source='<img src="/hero.png?width=3840"><img src="/other.png">'
        candidate='<style>.hero{background-image:url(/hero.png?width=1080)}</style>'
        result=self.measure(source,candidate)
        self.assertEqual(result['images_percent'],50)
        self.assertEqual(result['image_element_percent'],0)
        self.assertEqual(result['css_image_equivalents'],['https://example.test/hero.png?width=3840'])
        self.assertEqual(result['missing_image_examples'],['https://example.test/other.png'])


if __name__=='__main__':
    unittest.main()
