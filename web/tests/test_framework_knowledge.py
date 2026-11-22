import unittest

from framework_knowledge import retrieve_framework_knowledge
from remediation_jobs import complete_html_response, reconstruction_inventory
from remediation_jobs import content_retention
from remediation_jobs import serialize_reconstruction_inventory, generator_failure_evidence
from remediation_jobs import observed_document_media, rendered_media_retention, standalone_reconstruction


class FrameworkKnowledgeTests(unittest.TestCase):
    def test_component_lookup_avoids_substring_false_matches(self):
        units=retrieve_framework_knowledge({'signals':['platform','navigationx','cardinality','playlist']})
        self.assertEqual({item['component'] for item in units},{'document'})
        units=retrieve_framework_knowledge({'signals':['navbar-expand-lg','news-card','form-control']})
        self.assertTrue({'navigation','cards','forms'}.issubset({item['component'] for item in units}))
        self.assertIn('navigation',{item['component'] for item in retrieve_framework_knowledge({'signals':['navigation']})})

    def test_legacy_lookup_remains_small_and_source_grounded(self):
        units=retrieve_framework_knowledge({'signals':['nav','form','footer']})
        for item in units:
            self.assertTrue(item['source'].startswith('https://'))
            self.assertTrue(item['guidance'])
            self.assertNotIn('framework_version',item)
        form=next(item for item in units if item['component']=='forms')
        self.assertIn('action',form['guidance'])
        self.assertNotIn('cards',{item['component'] for item in units})

    def test_tailwind_does_not_receive_bootstrap_class_library(self):
        units=retrieve_framework_knowledge({'signals':['nav']},'tailwind')
        self.assertTrue(all('framework_version' not in item for item in units))

    def test_fragment_route_keeps_large_inventory_without_whole_page_context(self):
        import json
        inventory={'document_text':'x'*180001,'images':[{'url':'https://example.org/image.png'}]}
        context=json.loads(serialize_reconstruction_inventory(inventory,fragmented=True))
        self.assertEqual(context['mode'],'fragmented')
        self.assertEqual(context['counts']['images'],1)
        self.assertEqual(len(inventory['document_text']),180001)
        self.assertEqual(json.loads(serialize_reconstruction_inventory(inventory)),inventory)

    def test_media_evidence_includes_backgrounds_not_script_strings(self):
        urls=observed_document_media('<div style="background-image:url(/hero.jpg)"></div><script>const unused="https://test/unused.jpg"</script>',"https://example.test/")
        self.assertEqual(urls,{"https://example.test/hero.jpg"})
        result=rendered_media_retention('<img src="/hero.jpg">','<div style="background:url(/hero.jpg)"></div>',"https://example.test/")
        self.assertEqual(result["dynamic_images_percent"],100)

    def test_current_rendered_measurement_credits_stylesheet_assets_with_same_source_denominator(self):
        source='<img src="/hero.jpg"><img src="/other.jpg">'
        candidate='<style>.hero {background-image:url("/hero.jpg")}</style><div class="hero"></div><script>const unused="/other.jpg"</script>'
        legacy=rendered_media_retention(source,candidate,'https://example.test/')
        current=rendered_media_retention(source,candidate,'https://example.test/',image_asset_equivalence=True)
        self.assertEqual(legacy['dynamic_images_required'],2)
        self.assertEqual(current['dynamic_images_required'],2)
        self.assertEqual(legacy['dynamic_images_percent'],0)
        self.assertEqual(current['dynamic_images_percent'],50)
        self.assertEqual(current['dynamic_images_retained'],1)
        self.assertIn('not visual equivalence',current['dynamic_image_measurement'])

    def test_standalone_skip_link_does_not_navigate_back_to_original(self):
        html=standalone_reconstruction('<base href="https://example.test/page/"><a href="https://example.test/page/#main">Skip</a><img src="/hero.jpg"><main id="main"></main>',"https://example.test/page/")
        self.assertNotIn("<base",html)
        self.assertIn('href="#main"',html)
        self.assertIn('src="https://example.test/hero.jpg"',html)
    def test_complete_text_and_form_contract_are_retained(self):
        inventory=reconstruction_inventory('<div>Contenido fuera de párrafos</div><form action="/send" method="post"><label for="email">Correo</label><input id="email" name="email" required></form>',"https://example.test/")
        self.assertIn("Contenido fuera de párrafos",inventory["document_text"])
        self.assertEqual(inventory["forms"][0]["method"],"post")
        self.assertEqual(inventory["controls"][0]["label"],"Correo")
        self.assertTrue(inventory["controls"][0]["required"])

    def test_inventory_budget_never_silently_truncates(self):
        with self.assertRaisesRegex(ValueError,"No truncated page"):
            serialize_reconstruction_inventory({"document_text":"x"*200},limit=50)

    def test_localized_evidence_removes_recommendations_only(self):
        evidence=[{"rule":"color-contrast","description":"fix contrast","nodes":[{"target":["#title"],"html":"<h1 id=title>Title</h1>","failureSummary":"Change foreground"}]}]
        result=generator_failure_evidence(evidence,"localized")
        self.assertEqual(result[0]["nodes"][0]["target"],["#title"])
        self.assertNotIn("failureSummary",result[0]["nodes"][0])
        self.assertEqual(generator_failure_evidence(evidence,"guided"),evidence)
    def test_inventory_separates_page_assets_and_controls(self):
        inventory=reconstruction_inventory("""<!doctype html><html lang='es'><head><title>Facultad</title></head><body>
          <nav><a href='/inicio'>Inicio</a></nav><main><h1>Noticias</h1>
          <img src='/banner.jpg' alt='Convocatoria'><form action='/buscar'><label>Buscar <input name='q'></label></form>
          </main></body></html>""","https://www.uv.mx/fei/")
        self.assertEqual(inventory["title"],"Facultad")
        self.assertEqual(inventory["links"][0]["url"],"https://www.uv.mx/inicio")
        self.assertEqual(inventory["images"][0]["url"],"https://www.uv.mx/banner.jpg")
        self.assertEqual(inventory["controls"][0]["name"],"q")

    def test_inventory_finds_slider_assets_embedded_in_script(self):
        inventory=reconstruction_inventory('<script>const slide="https://cdn.test/banner.jpg"</script>')
        self.assertEqual(inventory["media_assets"],["https://cdn.test/banner.jpg"])

    def test_retrieval_returns_components_not_page_templates(self):
        items=retrieve_framework_knowledge({"signals":["nav","carousel","form","img"]},"bootstrap")
        names={item["component"] for item in items}
        self.assertTrue({"navigation","hero","forms","media"}.issubset(names))
        self.assertTrue(all("<!doctype" not in item["guidance"].lower() for item in items))

    def test_complete_html_removes_markdown_fence(self):
        result=complete_html_response("```html\n<!doctype html><html><body>OK</body></html>\n```")
        self.assertTrue(result.startswith("<!doctype html>"))
        self.assertTrue(result.endswith("</html>"))

    def test_repeated_responsive_image_is_one_retained_asset(self):
        original='<img src="/logo.png" alt="Logo"><img src="/logo.png" alt="Logo">'
        candidate='<img src="https://example.test/logo.png" alt="Logo">'
        result=content_retention(original,candidate,"https://example.test/")
        self.assertEqual(result["images_percent"],100.0)
        self.assertEqual(result["original_images"],1)


if __name__ == "__main__":
    unittest.main()
