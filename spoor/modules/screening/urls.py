from django.urls import path

from spoor.modules.screening.views import ScreeningView

app_name = "screening"

urlpatterns = [
    path("screening/", ScreeningView.as_view(), name="screen"),
]
