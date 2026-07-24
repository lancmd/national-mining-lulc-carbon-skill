"""Exercise locale-aware layout lookup and exact string category comparisons without ArcPy."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from arcgis_ops import layout_element, renderer_report  # noqa: E402


class Element:
    def __init__(self, name: str): self.name = name


class Layout:
    def __init__(self):
        self.elements = {
            "TEXT_ELEMENT": [Element("标题")], "LEGEND_ELEMENT": [Element("图例")],
            "MAPFRAME_ELEMENT": [Element("主地图")],
        }
    def listElements(self, element_type: str, name: str | None = None):
        values = self.elements[element_type]
        return values if name is None else [item for item in values if item.name == name]


class RendererItem:
    def __init__(self, values): self.label, self.values = "class", values


class Layer:
    name = "LULC"
    class Symbology:
        class Renderer:
            type = "UniqueValueRenderer"
            class Group:
                items = [RendererItem("10"), RendererItem([["2"]])]
            groups = [Group()]
            classBreaks = []
        renderer = Renderer()
    symbology = Symbology()


layout = Layout()
assert layout_element(layout, "TEXT_ELEMENT", "title").name == "标题"
assert layout_element(layout, "LEGEND_ELEMENT", "legend").name == "图例"
assert layout_element(layout, "MAPFRAME_ELEMENT", "map frame").name == "主地图"
report = renderer_report(Layer(), {"kind": "lulc", "expected_codes": [1, 2, 10]})
assert report["missing_codes"] == [1], report
assert report["category_codes"] == ["10", "2"], report

print('{"status":"completed","checks":["Chinese ArcGIS layout aliases","whole category string matching"]}')
