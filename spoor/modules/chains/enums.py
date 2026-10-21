from django.db import models


class ChainFamily(models.TextChoices):
    """Address and transaction formats are shared within a family."""

    TRON = "tron", "TRON"
    EVM = "evm", "EVM"
