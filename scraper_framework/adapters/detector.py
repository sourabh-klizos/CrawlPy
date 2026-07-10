from __future__ import annotations

from importlib import import_module

from bs4 import BeautifulSoup

from adapters.base.base_adapter import BaseAdapter
from adapters.generic.adapter import GenericAdapter


def build_adapters() -> list[BaseAdapter]:
    adapter_specs = [
        ("adapters.accela.adapter", "AccelaAdapter"),
        ("adapters.mygovernmentonline.adapter", "MyGovernmentOnlineAdapter"),
        ("adapters.tyler_energov.adapter", "TylerEnerGovAdapter"),
        ("adapters.opengov.adapter", "OpenGovAdapter"),
        ("adapters.arcgis.adapter", "ArcGISAdapter"),
        ("adapters.civicplus.adapter", "CivicPlusAdapter"),
        ("adapters.iworq_platform.adapter", "IworqPlatformAdapter"),
    ]
    adapters: list[BaseAdapter] = []

    for module_path, class_name in adapter_specs:
        try:
            module = import_module(module_path)
            adapter_class = getattr(module, class_name)
        except ModuleNotFoundError:
            continue
        adapters.append(adapter_class())

    return adapters


class AdapterDetector:
    def __init__(self, adapters: list[BaseAdapter]) -> None:
        self.adapters = adapters
        self.fallback = GenericAdapter()

    def detect(self, url: str, html: str, soup: BeautifulSoup) -> BaseAdapter:
        for adapter in self.adapters:
            if adapter.can_handle(url, html, soup):
                return adapter
        return self.fallback
