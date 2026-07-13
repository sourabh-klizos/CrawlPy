from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scraper_framework.adapters.tyler_energov_import.push_service import TylerEnerGovPushService


class _FakeStore:
    def find_documents(self, collection_name, query=None, sort=None, limit=None):
        documents = [
            {
                "normalized_data": {
                    "permit_number": "BLDC-000108-2025",
                    "permit_type": "Building New Construction (Commercial)",
                    "status": "Issued",
                    "address": "909 Stans Way Rougemont NC 27572",
                    "issued_date": "2026-01-20T12:39:12",
                },
                "raw_data": {"CaseNumber": "BLDC-000108-2025"},
            }
        ]
        if limit:
            return documents[:limit]
        return documents


class _FakeAdminClient:
    def __init__(self):
        self.pushed_payload = None

    def build_payload_from_permit_documents(self, **kwargs):
        return {
            "provider": kwargs["provider"],
            "state": kwargs["state"],
            "county": kwargs["county"],
            "agency": kwargs["agency"],
            "module": kwargs["module"],
            "source_url": kwargs["source_url"],
            "fips": kwargs["fips"],
            "records": [{"record_number": "BLDC-000108-2025"}],
        }

    def push_payload(self, payload):
        self.pushed_payload = payload
        return {"ok": True}


def test_push_service_dry_run_builds_api_compatible_payload() -> None:
    service = TylerEnerGovPushService(store=_FakeStore(), admin_client=_FakeAdminClient())

    result = service.run(execute=False)

    assert result["mode"] == "dry_run"
    assert result["payload"]["provider"] == "tyler_energov"
    assert result["payload"]["county"] == "Person County"
    assert result["payload"]["records"] == [{"record_number": "BLDC-000108-2025"}]


def test_push_service_execute_posts_payload() -> None:
    admin_client = _FakeAdminClient()
    service = TylerEnerGovPushService(store=_FakeStore(), admin_client=admin_client)

    result = service.run(execute=True)

    assert result["mode"] == "execute"
    assert admin_client.pushed_payload == result["payload"]
    assert result["response"] == {"ok": True}
