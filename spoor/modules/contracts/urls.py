from django.urls import path

from spoor.modules.contracts.views import ContractDetailView, ContractListView, TraceDeployerView

app_name = "contracts"

urlpatterns = [
    path("contracts/", ContractListView.as_view(), name="contract_list"),
    path("contracts/<uuid:pk>/", ContractDetailView.as_view(), name="contract_detail"),
    path("contracts/<uuid:pk>/trace/", TraceDeployerView.as_view(), name="trace_deployer"),
]
