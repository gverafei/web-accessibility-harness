import unittest
from urllib.parse import urljoin
from resource_srcset import rewrite
class SrcsetTests(unittest.TestCase):
 def test_harness_respects_declared_base_and_is_idempotent(self):
  from harness.html_tools import absolutize_resources
  from bs4 import BeautifulSoup
  html='<base href="/about/"><link rel="stylesheet" href="static/main.css"><img src="img/a.png" srcset="img/b,w_2.png 2x"><style>x{background:url(img/a.png)}</style>'
  output=absolutize_resources(html,'https://example.org/about/enterprise/')
  soup=BeautifulSoup(output,'html.parser')
  self.assertEqual(soup.base['href'],'https://example.org/about/')
  self.assertEqual(soup.link['href'],'https://example.org/about/static/main.css')
  self.assertEqual(soup.img['src'],'https://example.org/about/img/a.png')
  self.assertIn('https://example.org/about/img/b,w_2.png',soup.img['srcset'])
  self.assertIn('https://example.org/about/img/a.png',soup.style.string)
  self.assertEqual(absolutize_resources(output,'https://example.org/about/enterprise/'),output)
 def test_commas_in_cloudinary_and_media_urls_remain_inside_the_candidate(self):
  original='https://media.example.org/w_120,c_limit/image.jpg 120w, images/w_240,c_limit/image.jpg 240w'
  self.assertEqual(rewrite(original,lambda u:urljoin('https://example.org/',u)),'https://media.example.org/w_120,c_limit/image.jpg 120w, https://example.org/images/w_240,c_limit/image.jpg 240w')
 def test_empty_entries_trailing_delimiters_and_data_urls(self):
  self.assertEqual(rewrite(' , a.jpg 1x, , b.jpg 2x, ',lambda u:u),'a.jpg 1x, b.jpg 2x')
  self.assertEqual(rewrite('a.jpg, b.jpg,',lambda u:u),'a.jpg, b.jpg')
  original='data:image/png;base64,AAA 1x';self.assertEqual(rewrite(original,lambda u:'changed'),original)
 def test_both_remediation_preparers_preserve_the_same_srcset(self):
  from remediation_jobs import absolutize_resources as restored
  from harness.html_tools import absolutize_resources as harness
  from bs4 import BeautifulSoup
  html='<img srcset="image,w_120.jpg 120w, image,w_240.jpg 240w">'
  for prepare in (restored,harness):self.assertEqual(BeautifulSoup(prepare(html,'https://example.org/'),'html.parser').img['srcset'],'https://example.org/image,w_120.jpg 120w, https://example.org/image,w_240.jpg 240w')
