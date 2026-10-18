import pytest

from spoor.modules.cases.enums import CaseEventType, CaseType
from spoor.modules.cases.models import Case, CaseEvent


@pytest.fixture
def analyst(django_user_model):
    return django_user_model.objects.create_user("analyst", password="pw-for-tests")


@pytest.mark.django_db
class TestCaseHistory:
    def test_opening_a_case_records_who_opened_it(self, analyst):
        case = Case.create_case(analyst, name="Exchange hack", case_type=CaseType.HACK)

        event = case.events.get()
        assert event.event_type == CaseEventType.CREATED
        assert event.actor == analyst

    def test_events_cannot_be_rewritten(self, analyst):
        """History that can be edited is not history; corrections are new events."""
        case = Case.create_case(analyst, name="Case", case_type=CaseType.OTHER)
        event = case.events.get()

        event.summary = "Something else"
        with pytest.raises(ValueError):
            event.save()

    def test_admin_shows_events_but_cannot_change_them(self, admin_client, analyst):
        case = Case.create_case(analyst, name="Case", case_type=CaseType.OTHER)
        event = case.events.get()
        url = f"/admin/cases/caseevent/{event.pk}/change/"

        assert admin_client.get(url).status_code == 200
        assert admin_client.post(url, {"summary": "edited"}).status_code == 403


@pytest.mark.django_db
class TestCasePages:
    def test_opening_a_case_from_the_list_page(self, client, analyst):
        client.force_login(analyst)

        response = client.post(
            "/cases/", {"name": "Romance scam", "case_type": CaseType.ROMANCE, "description": ""}
        )

        case = Case.objects.get()
        assert response.url == f"/cases/{case.pk}/"
        assert case.created_by == analyst

    def test_case_page_shows_its_history(self, client, analyst):
        client.force_login(analyst)
        case = Case.create_case(analyst, name="Case", case_type=CaseType.OTHER)
        CaseEvent.record(case, analyst, CaseEventType.NOTE_ADDED, "Noted an address.")

        response = client.get(f"/cases/{case.pk}/")

        assert [e.summary for e in response.context["events"]] == [
            "Noted an address.",
            'Opened case "Case".',
        ]
