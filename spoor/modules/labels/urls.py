from django.urls import path

from spoor.modules.labels.views import LabelListView

app_name = "labels"

urlpatterns = [
    path("labels/", LabelListView.as_view(), name="label_list"),
]
