from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from lamp_character import simulator


class SimulatorCleanupTests(unittest.TestCase):
    def test_initialization_failure_disconnects_pybullet_client(self):
        with tempfile.TemporaryDirectory() as directory:
            urdf = Path(directory) / "robot.urdf"
            urdf.write_text("<robot name='test'/>", encoding="utf-8")
            with (
                mock.patch.object(simulator.p, "connect", return_value=17),
                mock.patch.object(
                    simulator.p,
                    "setAdditionalSearchPath",
                    side_effect=RuntimeError("initialization failed"),
                ),
                mock.patch.object(simulator.p, "disconnect") as disconnect,
            ):
                with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                    simulator.LampSimulator(urdf)

        disconnect.assert_called_once_with(physicsClientId=17)


if __name__ == "__main__":
    unittest.main()
