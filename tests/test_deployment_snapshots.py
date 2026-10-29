import sqlite3
import tempfile
from pathlib import Path
import unittest

from tools.deployment.snapshot_sqlite import snapshot


class DeploymentSnapshots(unittest.TestCase):
    def test_live_wal_snapshot_is_consistent_and_never_overwrites_an_existing_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.sqlite3'
            destination = Path(folder) / 'snapshot.sqlite3'
            writer = sqlite3.connect(source)
            try:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('CREATE TABLE records (id TEXT PRIMARY KEY, hash TEXT)')
                writer.execute("INSERT INTO records VALUES ('saved','original-hash')")
                writer.commit()
                result = snapshot(source, destination)
                self.assertEqual(result['table_counts'], {'records': 1})
                writer.execute("INSERT INTO records VALUES ('later','later-hash')")
                writer.commit()
                with sqlite3.connect(destination) as copied:
                    self.assertEqual(copied.execute('SELECT * FROM records').fetchall(),
                                     [('saved', 'original-hash')])
                with self.assertRaises(FileExistsError):
                    snapshot(source, destination)
                self.assertEqual(writer.execute('SELECT COUNT(*) FROM records').fetchone()[0], 2)
            finally:
                writer.close()


if __name__ == '__main__':
    unittest.main()
