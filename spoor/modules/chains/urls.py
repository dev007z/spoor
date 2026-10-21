from django.urls import path

from spoor.modules.chains.views import AddressTransfersView, EvidenceView

app_name = "chains"

urlpatterns = [
    path("transfers/", AddressTransfersView.as_view(), name="address_transfers"),
    path("evidence/<uuid:pk>/", EvidenceView.as_view(), name="evidence"),
]
