import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "deploy" / "bundle.py"


class DeploymentBundleTests(unittest.TestCase):
    def test_update_preserves_configuration_and_runtime_data(self):
        self.check_bundle(with_state=False)

    def test_initial_migration_carries_configuration_and_runtime_data(self):
        self.check_bundle(with_state=True)

    def check_bundle(self, with_state):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {
                "main.py": "print('bot')",
                "deploy/requirements-linux.txt": "ncatbot5==5.5.6",
                "plugins/as812/main.py": "print('plugin')",
                "plugins/as812/assets/cat.png": "image",
                "plugins/steam/assets/fonts/manifest.json": "{}",
                "plugins/steam/config.example.json": "{}",
                "config.yaml": "token: local-secret",
                "plugins/as812/config/config.yaml": "key: local-secret",
                "plugins/steam/config.json": "{\"key\":\"secret\"}",
                "plugins/as812/rag/rag_data/chroma_db/chroma.sqlite3": "database",
                "plugins/as812/rag/rag_data/chroma_db/index.bin": "vector",
                "plugins/mh/data/_team_codes.json": "{}",
                "data/rbac.json": "{}",
                "memory/conversation.txt": "conversation",
                "plugins/as812/logs/private.log": "private messages",
                "plugins/as812/__pycache__/main.pyc": "compiled",
                "plugins/as812/.env": "SECRET=private",
                "napcat/launcher.bat": "Windows launcher",
                ".venv/Scripts/python.exe": "Windows interpreter",
            }
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            output = root / "bundle.tar.gz"
            args = [sys.executable, str(SCRIPT), "--root", str(root), "--output", str(output)]
            if with_state:
                args.append("--with-state")
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with tarfile.open(output) as archive:
                names = set(archive.getnames())
                self.assertEqual(archive.extractfile("main.py").read(), b"print('bot')")
            code = {
                "main.py", "deploy/requirements-linux.txt", "plugins/as812/main.py",
                "plugins/as812/assets/cat.png", "plugins/steam/assets/fonts/manifest.json",
                "plugins/steam/config.example.json",
            }
            state = {
                "config.yaml", "plugins/as812/config/config.yaml", "plugins/steam/config.json",
                "plugins/as812/rag/rag_data/chroma_db/chroma.sqlite3",
                "plugins/as812/rag/rag_data/chroma_db/index.bin",
                "plugins/mh/data/_team_codes.json", "data/rbac.json", "memory/conversation.txt",
            }
            self.assertEqual(names, code | state if with_state else code)


if __name__ == "__main__":
    unittest.main()
