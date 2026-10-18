"""Issue a frozen report for a trace run.

The report is rendered once to self-contained HTML (inline styles, the graph as an
embedded image) and stored as issued, with a manifest of every provider response it
cites and that manifest's SHA-256. A PDF is rendered from the same HTML when
WeasyPrint's system libraries are present (the Docker image and CI); elsewhere the
stored HTML is the report.
"""

import base64
import binascii
import hashlib
import json
from importlib.metadata import version

from django.template.loader import render_to_string
from django.utils import timezone

from spoor.modules.cases.enums import CaseEventType
from spoor.modules.cases.models import CaseEvent
from spoor.modules.chains.models import RawResponse
from spoor.modules.reports.models import ReportExport
from spoor.modules.tracing.summary import summarize_run

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_GRAPH_IMAGE_BYTES = 5 * 1024 * 1024


class InvalidGraphImageError(ValueError):
    pass


def decode_graph_image(data_url):
    """The graph snapshot as raw PNG bytes, or None. Only PNG data URLs are accepted."""
    if not data_url:
        return None
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise InvalidGraphImageError("The graph image must be a PNG data URL.")
    try:
        image = base64.b64decode(data_url.removeprefix(prefix), validate=True)
    except binascii.Error as exc:
        raise InvalidGraphImageError("The graph image is not valid base64.") from exc
    if not image.startswith(PNG_SIGNATURE) or len(image) > MAX_GRAPH_IMAGE_BYTES:
        raise InvalidGraphImageError("The graph image must be a PNG under 5 MB.")
    return image


def issue_report(run, user, graph_image=None):
    summary = summarize_run(run)
    sources = cited_responses(summary["edge_rows"])
    reference = {raw.pk: index for index, raw in enumerate(sources, start=1)}
    for row in summary["edge_rows"]:
        row["reference"] = reference[row["transfer"].raw_response_id]

    generated_at = timezone.now()
    manifest = build_manifest(run, sources, generated_at)
    manifest_sha256 = sha256_json(manifest)
    html = render_to_string(
        "reports/report.html",
        {
            **summary,
            "sources": sources,
            "generated_at": generated_at,
            "generated_by": user,
            "spoor_version": manifest["spoor_version"],
            "manifest_sha256": manifest_sha256,
            "graph_image": (
                f"data:image/png;base64,{base64.b64encode(graph_image).decode()}"
                if graph_image
                else None
            ),
        },
    )
    pdf, pdf_error = render_pdf(html)

    report = ReportExport.objects.create(
        run=run,
        created_by=user,
        html=html,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        pdf=pdf,
        pdf_sha256=hashlib.sha256(pdf).hexdigest() if pdf else "",
        pdf_error=pdf_error,
    )
    if run.case:
        CaseEvent.record(
            run.case,
            user,
            CaseEventType.REPORT_EXPORTED,
            f"Issued a report for a {run.direction} {run.token.symbol} trace.",
            trace_run=str(run.pk),
            report=str(report.pk),
            manifest_sha256=manifest_sha256,
        )
    return report


def cited_responses(edge_rows):
    """Each provider response behind a followed transfer, once, in order of first citation."""
    order = list(dict.fromkeys(row["transfer"].raw_response_id for row in edge_rows))
    responses = RawResponse.objects.filter(pk__in=order).defer("body").in_bulk()
    return [responses[pk] for pk in order]


def build_manifest(run, sources, generated_at):
    return {
        "spoor_version": version("spoor"),
        "generated_at": generated_at.isoformat(),
        "trace_run": str(run.pk),
        "chain": run.chain.key,
        "token": run.token.contract,
        "direction": run.direction,
        "window": [run.start.isoformat(), run.end.isoformat()],
        "max_hops": run.max_hops,
        "fan_out": run.fan_out,
        "min_amount_raw": str(run.min_amount),
        "seed_tx_hash": run.seed_tx_hash,
        "seeds": sorted(seed.address for seed in run.seeds.all()),
        "responses": [
            {
                "id": str(raw.pk),
                "source": raw.source,
                "endpoint": raw.endpoint,
                "params": raw.params,
                "retrieved_at": raw.retrieved_at.isoformat(),
                "body_sha256": raw.body_sha256,
            }
            for raw in sources
        ],
    }


def sha256_json(value):
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def render_pdf(html):
    """(pdf bytes, "") or (None, reason) when WeasyPrint's system libraries are missing."""
    try:
        # Imported here: loading WeasyPrint loads Pango, which may not be installed.
        from weasyprint import HTML
    except OSError:
        return None, (
            "PDF rendering is unavailable here (WeasyPrint needs Pango); "
            "the HTML report is complete."
        )
    return HTML(string=html).write_pdf(), ""
