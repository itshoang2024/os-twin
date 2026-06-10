import unittest
import json
import os
import subprocess
from pathlib import Path

class TestSubcommandManifest(unittest.TestCase):
    def setUp(self):
        agents_root = Path(__file__).resolve().parents[2]
        self.schema_path = agents_root / "schemas" / "subcommands-schema.json"
        self.validate_script = agents_root / "bin" / "validate-subcommands.sh"
        self.manifests = sorted((agents_root / "roles").glob("*/subcommands.json"))
        self.template_manifest = agents_root / "roles" / "_base" / "subcommands.json.template"

    def test_schema_exists(self):
        self.assertTrue(os.path.exists(self.schema_path))

    def test_validate_script_exists(self):
        self.assertTrue(os.path.exists(self.validate_script))

    def test_validate_role_manifests(self):
        self.assertGreater(len(self.manifests), 0)
        for manifest in self.manifests:
            with self.subTest(manifest=str(manifest)):
                result = subprocess.run(["bash", self.validate_script, manifest], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, f"{manifest} validation failed: {result.stderr}")

    def test_validate_template(self):
        # We need to replace placeholder for it to be valid if role name has constraints, 
        # but currently schema says role is just a string.
        # Actually, schema doesn't have a regex for role.
        result = subprocess.run(["bash", self.validate_script, self.template_manifest], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"Template manifest validation failed: {result.stderr}")

    def test_invalid_manifest(self):
        invalid_manifest = "/tmp/invalid_subcommands.json"
        with open(invalid_manifest, "w") as f:
            json.dump({"role": "test", "language": "invalid_lang", "subcommands": []}, f)
        
        result = subprocess.run(["bash", self.validate_script, invalid_manifest], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not one of ['python', 'powershell', 'bash', 'node']", result.stderr)
        os.remove(invalid_manifest)

if __name__ == "__main__":
    unittest.main()
