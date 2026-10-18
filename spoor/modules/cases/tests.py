import pytest

from spoor.modules.cases.enums import CaseEventType, CaseType
from spoor.modules.cases.models import AddressNote, Case, CaseEvent
from spoor.modules.chains.models import Address, Chain


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


@pytest.mark.django_db
class TestAddressNotes:
    @pytest.fixture
    def case(self, analyst):
        return Case.create_case(analyst, name="Case", case_type=CaseType.OTHER)

    @pytest.fixture
    def address(self):
        return Address.resolve(Chain.get_chain(key="bsc"), "0x" + "ab" * 20)

    def url(self, case):
        return f"/api/v1/cases/{case.pk}/notes/"

    def test_adding_a_note_records_it_in_the_case_history(self, client, analyst, case, address):
        client.force_login(analyst)

        response = client.post(
            self.url(case),
            {"address_id": str(address.pk), "text": "Looks like a payout wallet."},
            content_type="application/json",
        )

        assert response.status_code == 201
        assert response.json()["data"]["author"] == "analyst"
        event = case.events.get(event_type=CaseEventType.NOTE_ADDED)
        assert event.details["address"] == address.address

    def test_notes_are_listed_per_address_newest_first(self, client, analyst, case, address):
        client.force_login(analyst)
        other = Address.resolve(address.chain, "0x" + "cd" * 20)
        AddressNote.add_note(case, address, analyst, "first")
        AddressNote.add_note(case, address, analyst, "second")
        AddressNote.add_note(case, other, analyst, "elsewhere")

        body = client.get(self.url(case), {"address_id": str(address.pk)}).json()

        assert [note["text"] for note in body["data"]] == ["second", "first"]

    def test_empty_note_is_a_validation_error_in_the_envelope(self, client, analyst, case, address):
        client.force_login(analyst)

        response = client.post(
            self.url(case),
            {"address_id": str(address.pk), "text": ""},
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.json()["errors"] == ["text: This field may not be blank."]

    def test_notes_cannot_be_edited(self, analyst, case, address):
        note = AddressNote.add_note(case, address, analyst, "original")

        note.text = "rewritten"
        with pytest.raises(ValueError):
            note.save()

    def test_notes_api_requires_login(self, client, case):
        assert client.get(self.url(case), {"address_id": "x"}).status_code == 403
