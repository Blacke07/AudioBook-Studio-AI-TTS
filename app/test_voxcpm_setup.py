"""Setting up and linking the optional VoxCPM2 engine: fake folders and a fake installer; nothing is downloaded."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import engine_client
import voxcpm_setup as setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="voxcpm-setup-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / "voxcpm.json"
        for module, name, value in ((engine_client, "VOXCPM_CONFIG", self.config), (setup, "FOLDER", self.root / "voxcpm")):
            item = patch.object(module, name, value)
            item.start()
            self.addCleanup(item.stop)
        item = patch.object(engine_client, "close_engine")
        self.closed = item.start()
        self.addCleanup(item.stop)

    def environment(self, folder, weights=True):
        (folder / "model").mkdir(parents=True)
        (folder / "model" / "config.json").write_text("{}")
        if weights:
            (folder / "model" / "model.safetensors").write_bytes(b"x")
        python = setup.venv_python(folder)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"x")
        return python, folder / "model"

    def test_status_before_and_after_linking_and_unlinking(self):
        self.assertFalse(setup.status()["installed"])
        python, model = self.environment(self.root / "elsewhere")
        state = setup.link(f'"{python}"', model)
        self.assertTrue(state["installed"])
        self.assertEqual(json.loads(self.config.read_text()), {"python": str(python), "model": str(model)})
        self.closed.assert_called()
        self.assertFalse(setup.unlink()["installed"])
        self.assertFalse(self.config.exists())

    def test_linking_refuses_a_missing_python_or_a_model_folder_without_weights(self):
        python, model = self.environment(self.root / "a", weights=False)
        with self.assertRaisesRegex(ValueError, "model.safetensors"):
            setup.link(python, model)
        with self.assertRaisesRegex(ValueError, "python.exe"):
            setup.link(self.root / "nowhere" / "python.exe", model)
        with self.assertRaisesRegex(ValueError, "python.exe"):
            setup.link(model / "config.json", model)
        self.assertFalse(self.config.exists())

    def test_install_runs_each_step_in_order_and_links_the_result(self):
        folder = self.root / "voxcpm"
        commands = []

        def fake(command, step):
            commands.append((step, [str(part) for part in command]))
            if step.startswith("Creating"):
                setup.venv_python(folder).parent.mkdir(parents=True)
                setup.venv_python(folder).write_bytes(b"x")
            if step.startswith("Downloading"):
                (folder / "model").mkdir(parents=True)
                (folder / "model" / "config.json").write_text("{}")
                (folder / "model" / "model.safetensors").write_bytes(b"x")

        with patch.object(setup, "_run", side_effect=fake):
            setup.install(folder)
        self.assertEqual([step.split(" (")[0] for step, _ in commands],
                         ["Creating the environment", "Updating pip", "Installing PyTorch with CUDA",
                          "Installing VoxCPM2", "Downloading the VoxCPM2 model"])
        self.assertIn(setup.TORCH_INDEX, commands[2][1])
        self.assertTrue(setup.status()["installed"])

    def test_a_second_setup_is_refused_while_one_runs_and_a_failure_is_reported(self):
        release = []

        def slow(folder=None):
            while not release:
                time.sleep(0.01)
            raise RuntimeError("pip failed: no network")

        with patch.object(setup, "install", side_effect=slow):
            self.assertTrue(setup.start())
            self.assertFalse(setup.start())
            self.assertTrue(setup.status()["job"]["running"])
            release.append(1)
            for _ in range(200):
                if not setup.status()["job"]["running"]:
                    break
                time.sleep(0.01)
        job = setup.status()["job"]
        self.assertFalse(job["running"])
        self.assertIn("no network", job["error"])


if __name__ == "__main__":
    unittest.main()
