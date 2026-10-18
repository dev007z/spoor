import hashlib
from datetime import UTC, datetime

import pytest
from django.db import IntegrityError

from spoor.modules.chains.addresses import (
    InvalidAddressError,
    InvalidTxHashError,
    normalize_address,
    normalize_tx_hash,
)
from spoor.modules.chains.enums import ChainFamily
from spoor.modules.chains.models import Address, Chain, RawResponse, Token, Transfer

# USDT on TRON in its three common spellings.
USDT_TRON_BASE58 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_TRON_HEX = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
USDT_TRON_LOG_FORM = "0xa614f803b6fd780986a42c78ec9c7f77e6ded13c"

UINT256_MAX = 2**256 - 1


class TestTronAddressNormalization:
    @pytest.mark.parametrize("spelling", [USDT_TRON_BASE58, USDT_TRON_HEX, USDT_TRON_LOG_FORM])
    def test_every_spelling_maps_to_base58(self, spelling):
        assert normalize_address(ChainFamily.TRON, spelling) == USDT_TRON_BASE58

    def test_hex_input_is_case_insensitive(self):
        assert normalize_address(ChainFamily.TRON, USDT_TRON_HEX.upper()) == USDT_TRON_BASE58

    def test_corrupted_base58_fails_the_checksum(self):
        """A single mistyped character must be rejected, not silently become another address."""
        corrupted = USDT_TRON_BASE58[:-1] + "u"
        with pytest.raises(InvalidAddressError):
            normalize_address(ChainFamily.TRON, corrupted)

    def test_evm_address_with_wrong_length_is_rejected(self):
        with pytest.raises(InvalidAddressError):
            normalize_address(ChainFamily.TRON, "0x1234")


class TestEvmNormalization:
    def test_checksummed_address_is_lowercased(self):
        value = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        assert normalize_address(ChainFamily.EVM, value) == value.lower()

    def test_address_without_0x_prefix_is_rejected(self):
        """Bare hex is ambiguous with TRON log form, so EVM input must say what it is."""
        with pytest.raises(InvalidAddressError):
            normalize_address(ChainFamily.EVM, "dac17f958d2ee523a2206206994597c13d831ec7")

    def test_base58_address_is_rejected(self):
        with pytest.raises(InvalidAddressError):
            normalize_address(ChainFamily.EVM, USDT_TRON_BASE58)


class TestTxHashNormalization:
    HASH = "AB" * 32

    def test_evm_hash_is_lowercase_with_prefix(self):
        assert normalize_tx_hash(ChainFamily.EVM, self.HASH) == "0x" + "ab" * 32

    def test_tron_hash_is_lowercase_without_prefix(self):
        assert normalize_tx_hash(ChainFamily.TRON, "0x" + self.HASH) == "ab" * 32

    def test_short_hash_is_rejected(self):
        with pytest.raises(InvalidTxHashError):
            normalize_tx_hash(ChainFamily.EVM, "0xabc")


@pytest.mark.django_db
class TestSeededReferenceData:
    def test_supported_chains_are_seeded(self):
        assert set(Chain.objects.values_list("key", flat=True)) == {"tron", "bsc", "ethereum"}

    def test_seeded_token_contracts_are_in_canonical_form(self):
        """Seed data bypasses normalization, so it must already match what lookups produce."""
        for token in Token.objects.select_related("chain"):
            assert token.chain.normalize_address(token.contract) == token.contract

    def test_token_lookup_accepts_any_spelling(self):
        tron = Chain.get_chain(key="tron")
        assert Token.get_token(tron, USDT_TRON_HEX).symbol == "USDT"

    def test_explorer_links(self):
        bsc = Chain.get_chain(key="bsc")
        assert bsc.tx_url("0xabc") == "https://bscscan.com/tx/0xabc"


@pytest.mark.django_db
class TestAddressResolve:
    def test_different_spellings_resolve_to_one_row(self):
        tron = Chain.get_chain(key="tron")

        first = Address.resolve(tron, USDT_TRON_BASE58)
        second = Address.resolve(tron, USDT_TRON_LOG_FORM)

        assert first.pk == second.pk
        assert Address.objects.filter(chain=tron).count() == 1


@pytest.mark.django_db
class TestRawResponse:
    ENDPOINT = "https://api.example.test/v1/transfers"

    def record(self, params, body='{"data": []}', retrieved_at=None):
        return RawResponse.record(
            source="example",
            endpoint=self.ENDPOINT,
            params=params,
            status_code=200,
            body=body,
            retrieved_at=retrieved_at,
        )

    def test_credentials_are_never_stored(self):
        response = self.record({"address": "0xabc", "apikey": "SECRET", "Token": "SECRET"})

        response.refresh_from_db()
        assert response.params == {"address": "0xabc"}
        assert "SECRET" not in response.fingerprint

    def test_fingerprint_ignores_credentials(self):
        """Rotating an API key must not invalidate the cache."""
        with_key = RawResponse.compute_fingerprint(
            "example", self.ENDPOINT, {"a": 1, "apikey": "x"}
        )
        without_key = RawResponse.compute_fingerprint("example", self.ENDPOINT, {"a": 1})
        assert with_key == without_key

    def test_fingerprint_ignores_parameter_order(self):
        first = RawResponse.compute_fingerprint("example", self.ENDPOINT, {"a": 1, "b": 2})
        second = RawResponse.compute_fingerprint("example", self.ENDPOINT, {"b": 2, "a": 1})
        assert first == second

    def test_body_is_stored_byte_for_byte_with_its_hash(self):
        body = '{"b":1,  "a":2}'
        response = self.record({}, body=body)

        response.refresh_from_db()
        assert response.body == body
        assert response.body_sha256 == hashlib.sha256(body.encode()).hexdigest()

    def test_get_latest_returns_the_newest_matching_response(self):
        self.record({"page": 1}, body="old", retrieved_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.record({"page": 1}, body="new", retrieved_at=datetime(2026, 2, 1, tzinfo=UTC))
        self.record({"page": 2}, body="other page")

        latest = RawResponse.get_latest(
            source="example", endpoint=self.ENDPOINT, params={"page": 1}
        )

        assert latest.body == "new"

    def test_get_latest_returns_none_when_uncached(self):
        assert RawResponse.get_latest(source="example", endpoint=self.ENDPOINT, params={}) is None


@pytest.mark.django_db
class TestTransfer:
    @pytest.fixture
    def context(self):
        bsc = Chain.get_chain(key="bsc")
        return {
            "chain": bsc,
            "token": Token.objects.get(chain=bsc, symbol="USDT"),
            "from_address": Address.resolve(bsc, "0x" + "1" * 40),
            "to_address": Address.resolve(bsc, "0x" + "2" * 40),
            "raw_response": RawResponse.record(
                source="example", endpoint="https://x.test", params={}, status_code=200, body="{}"
            ),
            "block_number": 1,
            "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        }

    def test_uint256_max_amount_survives_the_database_exactly(self, context):
        """Amounts above 28 digits would be rounded by a float or the default decimal context."""
        transfer = Transfer.objects.create(
            tx_hash="0x" + "a" * 64, log_index=0, amount=UINT256_MAX, **context
        )

        transfer.refresh_from_db()
        assert int(transfer.amount) == UINT256_MAX

    def test_amount_units_uses_token_decimals(self, context):
        transfer = Transfer.objects.create(
            tx_hash="0x" + "a" * 64, log_index=0, amount=1_500_000_000_000_000_000, **context
        )

        assert str(transfer.amount_units) == "1.500000000000000000"

    def test_one_transaction_can_hold_several_transfers(self, context):
        tx_hash = "0x" + "b" * 64
        Transfer.objects.create(tx_hash=tx_hash, log_index=0, amount=1, **context)
        Transfer.objects.create(tx_hash=tx_hash, log_index=1, amount=2, **context)

        assert Transfer.objects.filter(tx_hash=tx_hash).count() == 2

    def test_the_same_transfer_event_cannot_be_stored_twice(self, context):
        tx_hash = "0x" + "c" * 64
        Transfer.objects.create(tx_hash=tx_hash, log_index=0, amount=1, **context)

        with pytest.raises(IntegrityError):
            Transfer.objects.create(tx_hash=tx_hash, log_index=0, amount=1, **context)


@pytest.mark.django_db
class TestEvidenceIsReadOnlyInAdmin:
    def test_even_a_superuser_cannot_edit_or_delete_stored_responses(self, admin_client):
        response = RawResponse.record(
            source="example", endpoint="https://x.test", params={}, status_code=200, body="{}"
        )
        change_url = f"/admin/chains/rawresponse/{response.pk}/change/"
        delete_url = f"/admin/chains/rawresponse/{response.pk}/delete/"

        assert admin_client.get(change_url).status_code == 200  # viewable
        assert admin_client.post(change_url, {"body": "tampered"}).status_code == 403
        assert admin_client.post(delete_url, {"post": "yes"}).status_code == 403

        response.refresh_from_db()
        assert response.body == "{}"
