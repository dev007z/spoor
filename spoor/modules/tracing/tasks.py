from celery import shared_task

from spoor.modules.tracing.engine import TraceEngine
from spoor.modules.tracing.models import TraceRun


@shared_task
def run_trace(run_id):
    TraceEngine(TraceRun.objects.get(pk=run_id)).execute()
