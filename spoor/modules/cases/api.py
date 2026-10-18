from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView

from spoor.common.responses import success_response
from spoor.modules.cases.models import AddressNote, Case
from spoor.modules.cases.serializers import (
    CreateAddressNoteSerializer,
    FetchAddressNotesSerializer,
)
from spoor.modules.chains.models import Address


def note_payload(note):
    return {
        "id": str(note.pk),
        "author": note.author.get_username(),
        "created_at": note.created_at.isoformat(),
        "text": note.text,
    }


class AddressNotesApi(APIView):
    """Notes on one address within a case: list them, or add one."""

    def get(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        query = FetchAddressNotesSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        address = get_object_or_404(Address, pk=query.validated_data["address_id"])
        notes = [note_payload(n) for n in AddressNote.fetch_notes(case, address)]
        return success_response(notes, message="Address notes.")

    def post(self, request, pk):
        case = get_object_or_404(Case, pk=pk)
        body = CreateAddressNoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        address = get_object_or_404(Address, pk=body.validated_data["address_id"])
        note = AddressNote.add_note(case, address, request.user, body.validated_data["text"])
        return success_response(
            note_payload(note), message="Note added.", status=status.HTTP_201_CREATED
        )
