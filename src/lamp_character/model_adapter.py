"""Prepare the supplied model for PyBullet without modifying source assets."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


def _convert_ascii_stl_to_obj(source: Path, destination: Path) -> None:
    """Convert the small supplied ASCII STL into a PyBullet-friendly OBJ."""

    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    index_by_vertex: dict[tuple[float, float, float], int] = {}
    pending: list[int] = []

    for raw_line in source.read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().split()
        if len(parts) != 4 or parts[0] != "vertex":
            continue
        vertex = (float(parts[1]), float(parts[2]), float(parts[3]))
        index = index_by_vertex.get(vertex)
        if index is None:
            vertices.append(vertex)
            index = len(vertices)  # OBJ indices are one-based.
            index_by_vertex[vertex] = index
        pending.append(index)
        if len(pending) == 3:
            faces.append((pending[0], pending[1], pending[2]))
            pending.clear()

    if not vertices or not faces or pending:
        raise ValueError(f"Unsupported or malformed ASCII STL: {source}")

    lines = ["# Generated from the supplied lamp_shade.stl for PyBullet"]
    lines.extend(f"v {x:.9g} {y:.9g} {z:.9g}" for x, y, z in vertices)
    lines.extend(f"f {a} {b} {c}" for a, b, c in faces)
    destination.write_text("\n".join(lines) + "\n", encoding="ascii")


def prepare_pybullet_urdf(source_urdf: Path) -> Path:
    """Return a generated URDF whose mesh format PyBullet renders reliably.

    The challenge's source URDF is kept byte-for-byte intact.  PyBullet's
    TinyRenderer cannot extract this particular ASCII STL on Windows, so the
    adapter makes an equivalent OBJ and points a generated URDF at it.  Tiny
    inertials are also added to fixed semantic links to avoid importer defaults.
    """

    source_urdf = source_urdf.resolve()
    source_mesh = source_urdf.parent / "assets" / "lamp_shade.stl"
    if not source_mesh.is_file():
        raise FileNotFoundError(f"Lamp shade mesh not found: {source_mesh}")

    project_root = source_urdf.parent.parent
    generated_dir = project_root / "output" / "generated_models"
    generated_dir.mkdir(parents=True, exist_ok=True)
    generated_mesh = generated_dir / "lamp_shade.obj"
    generated_urdf = generated_dir / "dummy_lamp_5dof_pybullet.urdf"

    newest_source = max(source_urdf.stat().st_mtime, source_mesh.stat().st_mtime)
    if (
        generated_mesh.is_file()
        and generated_urdf.is_file()
        and min(generated_mesh.stat().st_mtime, generated_urdf.stat().st_mtime)
        >= newest_source
    ):
        return generated_urdf

    _convert_ascii_stl_to_obj(source_mesh, generated_mesh)

    tree = ET.parse(source_urdf)
    root = tree.getroot()
    for mesh in root.findall(".//mesh"):
        if Path(mesh.attrib.get("filename", "")).name == source_mesh.name:
            mesh.set("filename", generated_mesh.name)

    for link in root.findall("link"):
        if link.find("inertial") is not None:
            continue
        inertial = ET.Element("inertial")
        ET.SubElement(inertial, "origin", xyz="0 0 0", rpy="0 0 0")
        ET.SubElement(inertial, "mass", value="0.001")
        ET.SubElement(
            inertial,
            "inertia",
            ixx="0.000001",
            ixy="0",
            ixz="0",
            iyy="0.000001",
            iyz="0",
            izz="0.000001",
        )
        link.insert(0, inertial)

    tree.write(generated_urdf, encoding="utf-8", xml_declaration=True)
    return generated_urdf
