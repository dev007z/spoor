from rest_framework import serializers


class FetchAddressNotesSerializer(serializers.Serializer):
    address_id = serializers.UUIDField()


class CreateAddressNoteSerializer(serializers.Serializer):
    address_id = serializers.UUIDField()
    text = serializers.CharField(max_length=5000)
