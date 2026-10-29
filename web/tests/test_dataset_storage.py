import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from dataset_storage import (
    DatasetImportError, add_dataset_to_warp, compact_observation_name, import_dataset,
    import_dataset_from_warp,
)


def upload(name, content):
    return FileStorage(stream=io.BytesIO(content), filename=name)


class DatasetStorageTests(unittest.TestCase):
    def test_vera_observations_receive_readable_unique_global_names(self):
        self.assertEqual(
            compact_observation_name("html/site-1/generated/gemini/html/template-no.html"),
            "Site 1 · Gemini – HTML – No template",
        )
        self.assertEqual(
            compact_observation_name("html/site-2/generated/gpt/markdown/template-yes.html"),
            "Site 2 · GPT-4o – Markdown – Template",
        )
        self.assertEqual(
            compact_observation_name("html/site-2/manual-correction.html"),
            "Site 2 · Manual correction",
        )

    def test_long_nested_names_are_compact_but_still_recognizable(self):
        path = "collection/participant-0001/remediations/" + "very-long-page-name-" * 12 + ".html"
        compact = compact_observation_name(path)
        self.assertLessEqual(len(compact), 120)
        self.assertTrue(compact.startswith("…/"))
        self.assertTrue(compact.endswith(".html"))

    def test_zip_needs_no_special_structure_or_manifest(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("notes/manifest.csv", "name,value\nsource,example\n")
            archive.writestr("pages/home.html", "<!doctype html><title>Home</title>")
            archive.writestr("deep/nested/about.htm", "<!doctype html><title>About</title>")
        archive_bytes.seek(0)
        with tempfile.TemporaryDirectory() as root, patch(
            "dataset_storage.DATASET_ROOT", Path(root)
        ):
            metadata, observations = import_dataset(
                FileStorage(stream=archive_bytes, filename="ordinary.zip"),
                [], None, "Ordinary HTML", "isolated",
            )
            self.assertEqual(metadata["observations"], 2)
            self.assertEqual(
                {row["observation_id"] for row in observations},
                {"pages/home.html", "deep/nested/about.htm"},
            )

    def test_zip_and_individual_files_cannot_be_combined(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("inside.html", "<title>Inside</title>")
        archive_bytes.seek(0)
        with tempfile.TemporaryDirectory() as root, patch(
            "dataset_storage.DATASET_ROOT", Path(root)
        ):
            with self.assertRaisesRegex(DatasetImportError, "either one ZIP"):
                import_dataset(
                    FileStorage(stream=archive_bytes, filename="pages.zip"),
                    [upload("outside.html", b"<title>Outside</title>")],
                    None, "Ambiguous", "isolated",
                )
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_individual_html_is_imported_with_research_metadata(self):
        with tempfile.TemporaryDirectory() as root, patch(
            "dataset_storage.DATASET_ROOT", Path(root)
        ):
            metadata, observations = import_dataset(
                None,
                [upload("sample.html", b"<!doctype html><title>Sample</title>")],
                upload(
                    "manifest.csv",
                    b"path,observation_id,pair_id,condition,stratum,expected_label\n"
                    b"sample.html,page-1,pair-1,original,forms,1\n",
                ),
                "Research dataset",
                "isolated",
            )
            self.assertEqual(metadata["observations"], 1)
            self.assertEqual(observations[0]["observation_id"], "page-1")
            self.assertEqual(observations[0]["pair_id"], "pair-1")
            self.assertIn("dataset-server:8080", observations[0]["served_url"])

    def test_zip_path_traversal_is_rejected_atomically(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("../outside.html", "<title>Unsafe</title>")
        archive_bytes.seek(0)
        with tempfile.TemporaryDirectory() as root, patch(
            "dataset_storage.DATASET_ROOT", Path(root)
        ):
            with self.assertRaises(DatasetImportError):
                import_dataset(
                    FileStorage(stream=archive_bytes, filename="unsafe.zip"),
                    [], None, "Unsafe", "isolated",
                )
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_manifest_failure_removes_entire_dataset(self):
        with tempfile.TemporaryDirectory() as root, patch(
            "dataset_storage.DATASET_ROOT", Path(root)
        ):
            with self.assertRaises(DatasetImportError):
                import_dataset(
                    None,
                    [upload("sample.html", b"<title>Sample</title>")],
                    upload("manifest.csv", b"path,expected_label\nsample.html,changed\n"),
                    "Invalid manifest",
                    "isolated",
                )
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_warp_round_trip_restores_dataset_with_new_internal_urls(self):
        with tempfile.TemporaryDirectory() as root, patch(
            "dataset_storage.DATASET_ROOT", Path(root)
        ):
            metadata, observations = import_dataset(
                None, [upload("sample.html", b"<title>Portable</title>")], None,
                "Portable", "isolated",
            )
            package_bytes = io.BytesIO()
            with zipfile.ZipFile(package_bytes, "w") as package:
                add_dataset_to_warp(package, metadata["storage_key"])
            package_bytes.seek(0)
            descriptor = {
                "content_sha256": metadata["content_sha256"],
                "resource_policy": "isolated",
                "observations": [{
                    "path": observations[0]["path"],
                    "observation_id": observations[0]["observation_id"],
                    "content_sha256": observations[0]["content_sha256"],
                }],
            }
            with zipfile.ZipFile(package_bytes) as package:
                restored_metadata, restored = import_dataset_from_warp(
                    package, descriptor, "Restored"
                )
            self.assertNotEqual(restored_metadata["storage_key"], metadata["storage_key"])
            self.assertEqual(restored[0]["content_sha256"], observations[0]["content_sha256"])
            self.assertIn(restored_metadata["storage_key"], restored[0]["served_url"])


if __name__ == "__main__":
    unittest.main()
