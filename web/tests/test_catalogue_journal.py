"""Catalogue startup preserves the storage administrator's journal policy."""
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from harness.store import Store


class CatalogueJournalTests(unittest.TestCase):
    def test_store_does_not_reenable_wal_on_a_rollback_catalogue(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Store(directory)
            with first.connect() as connection:
                self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
            with ThreadPoolExecutor(max_workers=5) as workers:
                list(workers.map(lambda number: Store(directory).append('fixture', {'number':number}), range(25)))
            final = Store(directory)
            self.assertEqual(len(final.list('fixture')), 25)
            with final.connect() as connection:
                self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
                self.assertEqual(connection.execute('PRAGMA quick_check').fetchone()[0], 'ok')

    def test_existing_native_wal_catalogue_is_not_reconfigured(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            with sqlite3.connect(store.path) as connection:
                connection.execute('PRAGMA journal_mode=WAL')
            store = Store(directory)
            with store.connect() as connection:
                self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
