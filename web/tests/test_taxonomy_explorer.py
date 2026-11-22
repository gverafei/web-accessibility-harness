import unittest
from unittest.mock import Mock,patch
from accessibility_taxonomy.explorer import catalog_rows,AXE
from accessibility_taxonomy.presentation import details

class TaxonomyExplorerTests(unittest.TestCase):
    def test_catalog_coverage_distinguishes_available_rules_from_profile(self):
        rows=catalog_rows('es');self.assertEqual(len(rows),72)
        self.assertEqual(len(catalog_rows(category='Semantic')),14)
        supported=[r for r in rows if r['category']=='Semantic' and r['support'] in ('Contextual judgment','Verified image judgment')]
        self.assertEqual(len(supported),14)
        self.assertEqual(len([r for r in rows if r['support']=='Outside the measurement profile']),0)
        self.assertEqual(AXE['version'],'4.13.0')
        self.assertEqual(next(r for r in catalog_rows(include_excluded=True) if r['id']=='video-captions-inaccurate')['support'],'Outside the study scope')
        self.assertTrue(all(r['criterion'] for r in rows))
        self.assertIn('contraste',catalog_rows('es',q='color-contrast')[0]['criterion'])
        self.assertEqual(catalog_rows('es',category='Semantic',q='contraste'),[])

    def test_operational_review_is_complete_and_inactive_rules_are_not_measured(self):
        from accessibility_taxonomy import CATALOG, CURATION
        from accessibility_taxonomy.inventory import inventory
        reviewed={r['type']:r for r in CURATION['criterion_review']}
        self.assertEqual(set(reviewed),{r['id'] for r in CATALOG['violations']})
        active=catalog_rows()
        self.assertEqual({c:sum(r['category']==c for r in active) for c in ('Syntactic','Semantic','Layout')},
                         {'Syntactic':52,'Semantic':14,'Layout':6})
        self.assertTrue(all(reviewed[r['id']]['detector'] and reviewed[r['id']]['evidence'] for r in active))
        html='<html><body><p><a id="link" href="/">Link</a></p><audio autoplay></audio></body></html>'
        raw={'violations':[{'id':'link-in-text-block','tags':['wcag141'],'nodes':[{'target':['#link'],'impact':'serious'}]},
                           {'id':'no-autoplay-audio','tags':['wcag142'],'nodes':[{'target':['audio'],'impact':'serious'}]},
                           {'id':'region','tags':['best-practice'],'nodes':[{'target':['body'],'impact':'moderate'}]}]}
        measured=inventory(html,raw,'https://example.org/')
        self.assertNotIn('no-autoplay-audio',{r['type'] for r in measured['opportunities']})
        self.assertNotIn('region',{r['type'] for r in measured['opportunities']})
        self.assertEqual(measured['summary']['categories']['Layout']['failed'],1)
        self.assertEqual(measured['summary']['categories']['Syntactic']['failed'],0)

    def test_readonly_route_filters_and_escapes_without_provider_calls(self):
        from main import create_app
        app=create_app({'TESTING':True})
        with app.test_client() as client:
            with client.session_transaction() as session:session['language']='es'
            page=client.get('/taxonomy?category=Semantic').get_data(as_text=True)
            self.assertIn('image-alt-not-descriptive',page)
            self.assertNotIn('id="color-contrast"',page)
            self.assertIn('Taxonomía',page)
            self.assertIn('Página 1 de 1 · 14 criterios',page)
            self.assertNotIn('name="source"',page)
            own=client.get('/taxonomy?source=all&size=100').get_data(as_text=True)
            self.assertNotIn('id="video-captions-inaccurate"',own)
            self.assertNotIn('id="no-autoplay-audio"',own)
            self.assertEqual(next(r for r in catalog_rows() if r['id']=='link-in-text-block')['category'],'Layout')
            self.assertEqual(next(r for r in catalog_rows() if r['id']=='target-size')['wcag'],['2.5.8'])
            self.assertIn('72 criterios',own)
            self.assertIn('aria-current="page"',page)
            escaped=client.get('/taxonomy?q=%3Cscript%3Ealert(1)%3C/script%3E').get_data(as_text=True)
            self.assertNotIn('<script>alert(1)</script>',escaped)
            self.assertIn('&lt;script&gt;',escaped)

    def test_pagination_preserves_filters_and_clamps_invalid_pages(self):
        from main import create_app
        from bs4 import BeautifulSoup
        app=create_app({'TESTING':True})
        with app.test_client() as client:
            doc=BeautifulSoup(client.get('/taxonomy?category=Semantic&size=5&page=2').data,'html.parser')
            rows=doc.select('.taxonomy-violation-table tbody tr[id]')
            self.assertEqual(len(rows),5)
            expected=catalog_rows(category='Semantic')[5:10]
            self.assertEqual([r['id'] for r in rows],[r['id'] for r in expected])
            link=doc.select_one('a[aria-label="Next page"]')['href']
            self.assertIn('category=Semantic',link);self.assertIn('size=5',link);self.assertIn('page=3',link)
            clamped=BeautifulSoup(client.get('/taxonomy?category=Layout&size=5&page=999').data,'html.parser')
            self.assertEqual(len(clamped.select('.taxonomy-violation-table tbody tr[id]')),1)
            empty=BeautifulSoup(client.get('/taxonomy?q=nonexistent-criterion&size=999&page=-3').data,'html.parser')
            self.assertEqual(len(empty.select('.taxonomy-violation-table tbody tr[id]')),0)
            self.assertIn('Page 1 of 1',empty.select_one('.measurement-pagination-status').get_text(' ',strip=True))

    def test_criteria_follow_the_resolved_interface_language(self):
        from main import create_app
        from bs4 import BeautifulSoup

        app = create_app({'TESTING': True, 'BABEL_DEFAULT_LOCALE': 'es'})
        with app.test_client() as client:
            for language, locale in ((None, 'es'), ('unsupported', 'en'), ('es', 'es')):
                with self.subTest(language=language):
                    with client.session_transaction() as session:
                        session.pop('language', None)
                        if language:
                            session['language'] = language
                    response = client.get('/taxonomy?q=image-alt-not-descriptive')
                    self.assertEqual(response.status_code, 200)
                    document = BeautifulSoup(response.data, 'html.parser')
                    criterion = document.select_one('#image-alt-not-descriptive td:nth-of-type(2)')
                    expected = catalog_rows(locale, q='image-alt-not-descriptive')[0]['criterion']
                    self.assertIn(expected, criterion.get_text(' ', strip=True))

    def test_alt_evidence_is_visible_not_replaced_with_empty_element_text(self):
        store=Mock();store.get.return_value={'data':{'opportunities':[{'type':'image-alt-not-descriptive','method':'decisions','status':'failed','context':{'element':{'attributes':{'alt':'Wrong label'},'text':''}}}]}}
        evidence=details({'retained_assessment_id':'a'},store)['rows'][0]['evidence']
        self.assertEqual(evidence[0]['text'],'Wrong label')

    def test_report_does_not_equate_new_semantic_opportunities_with_regression(self):
        from main import create_app
        from flask import render_template
        m={'original':{'categories':{'Semantic':{'judged':23,'failed':0,'unassessed':62}}},'retained':{'categories':{'Semantic':{'judged':26,'failed':2,'unassessed':62}}},'comparison':{'new_opportunities':{'categories':{'Semantic':{'failed':2}}}}}
        app=create_app({'TESTING':True})
        for phase in ('original','retained'):
            for category in ('Syntactic','Layout'):m[phase]['categories'][category]={'judged':1,'failed':0,'unassessed':0}
        with app.test_request_context():
            for template in ('_taxonomy_counts.html','_taxonomy_outcomes.html'):
                html=render_template(template,measurement=m)
                self.assertIn('23 → 26',html)
                self.assertIn('Semantic failures without a comparable prior judgment',html)
                self.assertIn('/taxonomy?category=Semantic',html)

    def test_image_usage_is_observed_without_following_destination(self):
        from accessibility_taxonomy.inventory import inventory
        from accessibility_taxonomy import RUBRICS
        html='<html><body><a href="/article"><img src="/picture.png" alt="News title"><h2>News title</h2></a></body></html>'
        row=next(r for r in inventory(html,{},'https://example.org/')['opportunities'] if r['type']=='image-alt-not-descriptive')
        usage=row['context']['image_usage']
        self.assertEqual(usage['link_text'],'News title')
        self.assertEqual(usage['link_href'],'https://example.org/article')
        self.assertIn('<h2>News title</h2>',usage['link_html'])
        self.assertIn('content OR purpose',RUBRICS['image-alt-not-descriptive'])
        self.assertIn('unvisited destination',RUBRICS['image-alt-not-descriptive'])
