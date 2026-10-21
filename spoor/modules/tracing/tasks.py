from celery import shared_task

from spoor.modules.tracing.engine import TraceEngine
from spoor.modules.tracing.models import TraceNode, TraceRun


@shared_task
def run_trace(run_id):
    TraceEngine(TraceRun.objects.get(pk=run_id)).execute()


@shared_task
def expand_node(node_id):
    node = TraceNode.objects.select_related("run__token__chain").get(pk=node_id)
    TraceEngine(node.run).execute(from_node=node)
