from __future__ import annotations

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
                "output": {"filename": "air-temp"},
            },
        },
        metrics_manifest={
            "version": "0.1",
            "t2m_yearly_mean_c": {"grid_id": "global_0p25"},
        },
    )
    assert layers[0]["asset_path"] == "maps/global_0p25/t2m_texture/air-temp.png"
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
