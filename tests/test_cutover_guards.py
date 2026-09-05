"""Cutover guards: no leftover dummy generators or light-theme tri-scale."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = ROOT / "frontend" / "src"
SERVICES = ROOT / "thaalam" / "services"

TRI_SCALE_HEXES = ("#16a34a", "#dc2626", "#d97706")
LIGHT_THEME_MARKERS = ("cormorant", "family=inter", "font-family: inter", '"inter"')

#: Off-white canvas and pastel orbs from the pre-redesign palette. New
#: surfaces are built from the :root tokens, so a literal hex here means
#: someone reached past the token set.
LIGHT_THEME_HEXES = (
    "#f5f5f5",
    "#fafafa",
    "#f0efed",
    "#e7e5e4",
    "#d6d3d1",
    "#a7e5d3",
    "#f4c5a8",
    "#c8b8e0",
    "#a8c8e8",
    "#e8b8c4",
)
DUMMY_MARKERS = (
    "generate_dummy",
    "dummy_chart",
    "synthetic_points",
    "mock_chart",
    "fake_points",
    "seeded_chart",
    "generate_synthetic",
)


def _iter_text(root: Path, suffixes: tuple[str, ...]):
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in suffixes:
            yield path


def _hits(root: Path, suffixes: tuple[str, ...], needles: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in _iter_text(root, suffixes):
        text = path.read_text(encoding="utf-8").lower()
        for needle in needles:
            if needle in text:
                found.append(f"{path.relative_to(ROOT).as_posix()}: {needle}")
    return found


def test_frontend_has_no_tri_scale_hexes():
    assert _hits(FRONTEND_SRC, (".ts", ".tsx", ".css"), TRI_SCALE_HEXES) == []


def test_frontend_has_no_leftover_light_theme_type():
    assert _hits(FRONTEND_SRC, (".ts", ".tsx", ".css"), LIGHT_THEME_MARKERS) == []
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8").lower()
    assert "cormorant" not in html
    assert "family=inter" not in html


def test_frontend_has_no_light_theme_palette():
    """Covers the auth and admin surfaces added after the redesign."""
    assert _hits(FRONTEND_SRC, (".ts", ".tsx", ".css"), LIGHT_THEME_HEXES) == []


def test_services_have_no_dummy_generators():
    assert _hits(SERVICES, (".py",), DUMMY_MARKERS) == []


def test_services_copy_never_says_population():
    assert _hits(SERVICES, (".py",), ("population",)) == []
