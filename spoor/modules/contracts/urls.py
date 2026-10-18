from django.urls import path

from spoor.modules.contracts.views import ContractDetailView, ContractListView

app_name = "contracts"

urlpatterns = [
    path("contracts/", ContractListView.as_view(), name="contract_list"),
    path("contracts/<uuid:pk>/", ContractDetailView.as_view(), name="contract_detail"),
]
