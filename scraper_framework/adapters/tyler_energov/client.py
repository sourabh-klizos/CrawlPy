try:
    from adapters.base.client import AdapterClients
except ModuleNotFoundError:
    from scraper_framework.adapters.base.client import AdapterClients


class TylerEnerGovAdapterClient(AdapterClients):
    pass
