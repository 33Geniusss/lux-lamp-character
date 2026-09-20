from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
URDF = ROOT / "robot" / "dummy_lamp_5dof.urdf"


class UrdfContractTests(unittest.TestCase):
    def test_supplied_mesh_and_urdf_exist(self) -> None:
        self.assertTrue(URDF.is_file())
        self.assertTrue((ROOT / "robot" / "assets" / "lamp_shade.stl").is_file())

    def test_five_movable_joints_and_semantic_links(self) -> None:
        root = ET.parse(URDF).getroot()
        movable = {
            joint.attrib["name"]
            for joint in root.findall("joint")
            if joint.attrib.get("type") != "fixed"
        }
        self.assertEqual(
            movable,
            {
                "base_yaw_joint",
                "shoulder_pitch_joint",
                "elbow_pitch_joint",
                "neck_yaw_joint",
                "head_pitch_joint",
            },
        )
        links = {link.attrib["name"] for link in root.findall("link")}
        self.assertTrue({"light_emitter_link", "camera_link", "speaker_link"} <= links)

    def test_ascii_stl_has_complete_triangles(self) -> None:
        mesh = ROOT / "robot" / "assets" / "lamp_shade.stl"
        vertex_lines = [
            line
            for line in mesh.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("vertex ")
        ]
        self.assertGreater(len(vertex_lines), 0)
        self.assertEqual(len(vertex_lines) % 3, 0)


if __name__ == "__main__":
    unittest.main()
