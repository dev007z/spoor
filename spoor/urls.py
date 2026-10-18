"""URL routes owned by the spoor package. Deployments include this at their root."""

from django.urls import include, path

from spoor.views import HomeView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("", include("spoor.modules.chains.urls")),
    path("", include("spoor.modules.cases.urls")),
    path("", include("spoor.modules.labels.urls")),
    path("", include("spoor.modules.tracing.urls")),
]
