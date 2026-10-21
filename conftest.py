import pytest


@pytest.fixture(autouse=True)
def plain_static_storage(settings):
    """Production uses a hashed manifest built by collectstatic, which tests never run."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
