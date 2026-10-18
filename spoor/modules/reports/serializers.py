from rest_framework import serializers


class IssueReportSerializer(serializers.Serializer):
    # A PNG data URL of the graph, as exported by the trace page; optional.
    graph_image = serializers.CharField(required=False, allow_blank=True, max_length=7_500_000)
