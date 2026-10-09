import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestLoginRequiredByDefault:
    def test_anonymous_user_is_redirected_to_login(self, client):
        """Every page requires login unless a view explicitly opts out."""
        response = client.get(reverse("home"))

        assert response.status_code == 302
        assert response.url.startswith(reverse("login"))

    def test_login_page_is_reachable_anonymously(self, client):
        response = client.get(reverse("login"))

        assert response.status_code == 200

    def test_authenticated_user_sees_home(self, client, django_user_model):
        user = django_user_model.objects.create_user(username="analyst", password="pw-for-tests")
        client.force_login(user)

        response = client.get(reverse("home"))

        assert response.status_code == 200
