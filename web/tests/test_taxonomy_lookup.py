import tempfile
import unittest

from harness.store import Store


class TaxonomyLookupTests(unittest.TestCase):
    def test_existing_evidence_is_indexed_without_changing_lookup_or_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            with store.connect() as db:
                db.execute('DROP INDEX taxonomy_supplement_lookup')
            for ident, kind, fingerprint in (
                ('first', 'taxonomy_assessment', 'same'),
                ('other', 'taxonomy_assessment', 'different'),
                ('second', 'taxonomy_assessment', 'same'),
                ('excluded', 'call_receipt', 'same'),
            ):
                store.append(kind, {'supplement_fingerprint': fingerprint}, ident=ident)
            query = ("SELECT id FROM records WHERE kind='taxonomy_assessment' "
                     "AND json_extract(payload,'$.supplement_fingerprint')=? ORDER BY created,id")
            before = store.list()
            with store.connect() as db:
                expected = [row['id'] for row in db.execute(query, ('same',))]
            migrated = Store(root)
            with migrated.connect() as db:
                actual = [row['id'] for row in db.execute(query, ('same',))]
                plan = ' '.join(row['detail'] for row in db.execute('EXPLAIN QUERY PLAN '+query, ('same',)))
            self.assertEqual(actual, ['first', 'second'])
            self.assertEqual(actual, expected)
            self.assertEqual(migrated.list(), before)
            self.assertIn('taxonomy_supplement_lookup', plan)
            self.assertNotIn('TEMP B-TREE', plan)


if __name__ == '__main__':
    unittest.main()
