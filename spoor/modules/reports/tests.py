import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from spoor.modules.cases.enums import CaseEventType, CaseType
from spoor.modules.cases.models import Case
from spoor.modules.chains.adapters.base import FetchResult, TransferRecord
from spoor.modules.chains.models import Address, RawResponse, Token
from spoor.modules.reports.builder import (
    InvalidGraphImageError,
    decode_graph_image,
    issue_report,
    render_pdf,
    sha256_json,
)
from spoor.modules.reports.models import ReportExport
from spoor.modules.tracing.engine import TraceEngine
from spoor.modules.tracing.models import TraceRun

T0 = datetime(2026, 1, 1, tzinfo=UTC)
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def pango_available():
    _, error = render_pdf("<p>probe</p>")
    return not error


def evm(name):
    return "0x" + name * 40


class TwoHops:
    """a sends 7 USDT to b, b sends 5 USDT to c, each from its own provider response."""

    def __init__(self):
        self.records = []
        for index, (sender, receiver, amount) in enumerate([("a", "b", 7), ("b", "c", 5)], 1):
            raw = RawResponse.record(
                source="test",
                endpoint=f"https://x.test/{index}",
                params={"page": index},
                status_code=200,
                body=f'{{"n":{index}}}',
            )
            self.records.append(
                TransferRecord(
                    tx_hash="0x" + format(index, "064x"),
                    log_index=index,
                    block_number=100 + index,
                    timestamp=T0 + timedelta(minutes=index),
                    from_address=evm(sender),
                    to_address=evm(receiver),
                    amount=amount * 10**18,
                    raw_response=raw,
                )
            )

    def get_token_transfers(self, address, token, start, end, max_records):
        records = [r for r in self.records if address in (r.from_address, r.to_address)]
        return FetchResult(records=records, complete=True)


@pytest.fixture
def run(admin_user):
    usdt = Token.objects.get(chain__key="bsc", symbol="USDT")
    case = Case.create_case(admin_user, name="Case", case_type=CaseType.OTHER)
    run = TraceRun.objects.create(token=usdt, case=case, start=T0, end=T0 + timedelta(hours=1))
    run.seeds.set([Address.resolve(usdt.chain, evm("a"))])
    TraceEngine(run, TwoHops()).execute()
    run.refresh_from_db()
    return run


@pytest.mark.django_db
class TestIssueReport:
    def test_report_cites_every_transfer_and_response(self, run, admin_user):
        report = issue_report(run, admin_user, TINY_PNG)

        assert "0x" + format(1, "064x") in report.html
        assert "7.000000000000000000" in report.html  # exact, never rounded
        assert "R2" in report.html
        assert [r["source"] for r in report.manifest["responses"]] == ["test", "test"]
        assert report.manifest_sha256 == sha256_json(report.manifest)
        assert report.manifest_sha256 in report.html
        assert "data:image/png;base64," in report.html

    def test_manifest_records_each_response_body_hash(self, run, admin_user):
        report = issue_report(run, admin_user)

        hashes = {r["body_sha256"] for r in report.manifest["responses"]}
        assert hashlib.sha256(b'{"n":1}').hexdigest() in hashes

    def test_issuing_is_recorded_in_the_case(self, run, admin_user):
        report = issue_report(run, admin_user)

        event = run.case.events.get(event_type=CaseEventType.REPORT_EXPORTED)
        assert event.details["report"] == str(report.pk)

    def test_issued_reports_are_frozen(self, run, admin_user):
        report = issue_report(run, admin_user)

        report.html = "<p>edited</p>"
        with pytest.raises(ValueError):
            report.save()

    @pytest.mark.skipif(not pango_available(), reason="WeasyPrint needs Pango (Docker and CI)")
    def test_renders_a_pdf_with_its_hash(self, run, admin_user):
        report = issue_report(run, admin_user, TINY_PNG)

        assert bytes(report.pdf).startswith(b"%PDF")
        assert report.pdf_sha256 == hashlib.sha256(bytes(report.pdf)).hexdigest()


class TestGraphImage:
    def test_accepts_a_png_data_url(self):
        data_url = "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()
        assert decode_graph_image(data_url) == TINY_PNG

    @pytest.mark.parametrize(
        "value",
        [
            "data:image/svg+xml;base64,PHN2Zz4=",
            "data:image/png;base64,not base64!",
            "data:image/png;base64," + base64.b64encode(b"GIF89a").decode(),
        ],
    )
    def test_rejects_anything_else(self, value):
        with pytest.raises(InvalidGraphImageError):
            decode_graph_image(value)


@pytest.mark.django_db
class TestReportEndpoints:
    def url(self, run):
        return f"/api/v1/traces/{run.pk}/reports/"

    def test_issue_returns_links_and_hash(self, admin_client, run):
        response = admin_client.post(self.url(run), {}, content_type="application/json")

        body = response.json()
        report = ReportExport.objects.get()
        assert response.status_code == 201
        assert body["data"]["report_url"] == f"/reports/{report.pk}/"
        assert body["data"]["manifest_sha256"] == report.manifest_sha256

    def test_refuses_while_the_trace_runs(self, admin_client, run):
        run.mark_running()

        response = admin_client.post(self.url(run), {}, content_type="application/json")

        assert response.status_code == 409

    def test_bad_graph_image_is_rejected(self, admin_client, run):
        response = admin_client.post(
            self.url(run),
            {"graph_image": "data:text/html,<script>"},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["error_code"] == "invalid_graph_image"

    def test_html_view_serves_the_report_as_issued(self, admin_client, run, admin_user):
        report = issue_report(run, admin_user)

        response = admin_client.get(f"/reports/{report.pk}/")

        assert response.content.decode() == report.html

    def test_pdf_view_is_404_without_a_pdf(self, admin_client, run, admin_user, monkeypatch):
        monkeypatch.setattr(
            "spoor.modules.reports.builder.render_pdf", lambda html: (None, "unavailable")
        )
        report = issue_report(run, admin_user)

        assert admin_client.get(f"/reports/{report.pk}/pdf/").status_code == 404
