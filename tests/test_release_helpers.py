from __future__ import annotations

from pathlib import Path

import pytest

from climate_api.release import (
    _build_release_layers,
    _resolve_texture_file_format,
    _resolve_texture_filename,
)


def test_resolve_texture_format_and_filename() -> None:
    assert _resolve_texture_file_format({}) == "png"
    assert _resolve_texture_file_format({"file_format": "WEBP"}) == "webp"
    assert _resolve_texture_file_format({"output": {"filename": "my-map.png"}}) == "png"
    assert _resolve_texture_filename(map_id="a", map_spec={}) == "a.png"
    assert _resolve_texture_filename(map_id="a", map_spec={"output": {"filename": "name"}}) == "name.png"
    assert _resolve_texture_filename(map_id="a", map_spec={"output": {"filename": "name.webp"}}) == "name.webp"

    with pytest.raises(ValueError, match="Unsupported texture file_format"):
        _resolve_texture_file_format({"file_format": "gif"})
    with pytest.raises(ValueError, match="does not match"):
        _resolve_texture_file_format(
            {"file_format": "webp", "output": {"filename": "map.png"}}
        )


def test_build_release_layers_success() -> None:
    layers = _build_release_layers(
        layers_manifest={
            "version": "0.1",
            "air": {
                "id": "air",
                "label": "Air Temperature",
                "map_id": "t2m_texture",
                "description": "desc",
                "opacity": 0.8,
            },
        },
        maps_manifest={
            "version": "0.1",
            "t2m_texture": {
                "type": "texture",
                "source_metric": "t2m_yearly_mean_c",
                "grid_id": "global_0p25",
                "output": {
                    "filename": "air-temp",
                    "mobile_filename": "air-temp-mobile",
                    "width": 1440,
                    "height": 681,
                    "mobile_width": 720,
                    "mobile_height": 341,
                },
            },
        },
        metrics_manifest={
            "version": "0.1",
            "t2m_yearly_mean_c": {"grid_id": "global_0p25"},
        },
    )
    assert layers[0]["asset_path"] == "maps/global_0p25/t2m_texture/air-temp.png"
    assert layers[0]["mobile_asset_path"] == "maps/global_0p25/t2m_texture/air-temp-mobile.png"
    assert layers[0]["asset_width"] == 1440
    assert layers[0]["asset_height"] == 681
    assert layers[0]["mobile_asset_width"] == 720
    assert layers[0]["mobile_asset_height"] == 341
    assert layers[0]["description"] == "desc"
    assert layers[0]["opacity"] == 0.8


def test_build_release_layers_validates_inputs() -> None:
    base_layers = {"layer": {"id": "layer", "label": "Layer", "map_id": "m1"}}
    with pytest.raises(ValueError, match="unknown map_id"):
        _build_release_layers(
            layers_manifest=base_layers,
            maps_manifest={},
            metrics_manifest={},
        )

    with pytest.raises(ValueError, match="non-texture"):
        _build_release_layers(
            layers_manifest=base_layers,
            maps_manifest={"m1": {"type": "score", "source_metric": "x"}},
            metrics_manifest={"x": {"grid_id": "global_0p25"}},
        )

    with pytest.raises(ValueError, match="unknown source_metric"):
        _build_release_layers(
            layers_manifest=base_layers,
            maps_manifest={"m1": {"type": "texture", "source_metric": "missing"}},
            metrics_manifest={},
        )

    with pytest.raises(ValueError, match="does not define a grid_id"):
        _build_release_layers(
            layers_manifest=base_layers,
            maps_manifest={"m1": {"type": "texture", "source_metric": "x"}},
            metrics_manifest={"x": {}},
        )


def test_build_release_layers_falls_back_to_asset_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_read_image_dimensions(path: Path) -> tuple[int, int] | None:
        name = path.name
        if name == "air-temp.webp":
            return (4096, 1935)
        if name == "air-temp-mobile.webp":
            return (2048, 968)
        return None

    monkeypatch.setattr(
        "climate_api.release._read_image_dimensions",
        _fake_read_image_dimensions,
    )

    layers = _build_release_layers(
        layers_manifest={
            "air": {
                "id": "air",
                "label": "Air Temperature",
                "map_id": "t2m_texture",
            },
        },
        maps_manifest={
            "t2m_texture": {
                "type": "texture",
                "source_metric": "t2m_yearly_mean_c",
                "grid_id": "global_0p25",
                "output": {
                    "filename": "air-temp.webp",
                    "mobile_filename": "air-temp-mobile.webp",
                },
            },
        },
        metrics_manifest={
            "t2m_yearly_mean_c": {"grid_id": "global_0p25"},
        },
        maps_root=Path("/tmp/release/maps"),
    )

    assert layers[0]["asset_width"] == 4096
    assert layers[0]["asset_height"] == 1935
    assert layers[0]["mobile_asset_width"] == 2048
    assert layers[0]["mobile_asset_height"] == 968
