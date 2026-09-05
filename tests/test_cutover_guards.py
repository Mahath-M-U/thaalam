"""Cutover guards: no leftover dummy generators or light-theme tri-scale."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = ROOT / "frontend" / "src"
SERVICES = ROOT / "thaalam" / "services"

TRI_SCALE_HEXES = ("#16a34a", "#dc2626", "#d97706")
LIGHT_THEME_MARKERS = ("cormorant", "family=inter", "font-family: inter", '"inter"')
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


def test_services_have_no_dummy_generators():
    assert _hits(SERVICES, (".py",), DUMMY_MARKERS) == []


def test_services_copy_never_says_population():
    assert _hits(SERVICES, (".py",), ("population",)) == []
