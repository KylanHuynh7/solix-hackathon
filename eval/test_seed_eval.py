import seed_eval
from contracts.schemas import Field, FieldStatus, Offer

LABELS = seed_eval.load_labels()


def _empty() -> Field:
    return Field(value=None, status=FieldStatus.needs_review, reason="no offer in this email")


def oracle(email, case) -> Offer:
    """Returns the hand-checked labels as the extraction."""
    name = next(k for k, v in LABELS.items() if v["message_id"] == email.message_id)
    lab = LABELS[name]
    if name not in seed_eval.OFFERS:
        e = _empty()
        return Offer(
            supplier_id="SUP-X", round=1, ndc=e, product=e, quantity=e, lots=[], expiry=e,
            unit_price=e, lead_time_days=e, storage=e, source_message_id=email.message_id,
        )
    return Offer(
        supplier_id="SUP-X", round=1,
        ndc=Field(**lab["ndc"]), product=_empty(), quantity=Field(**lab["quantity"]),
        lots=[Field(**x) for x in lab["lots"]], expiry=Field(**lab["expiry"]),
        unit_price=Field(**lab["unit_price"]), lead_time_days=_empty(), storage=_empty(),
        source_message_id=email.message_id,
    )


def test_oracle_scores_perfect():
    result = seed_eval.run(oracle)
    assert result["overall"]["accuracy_pct"] == 100.0
    assert result["overall"]["silent_errors"] == 0
    assert result["silent_errors"] == []
    assert result["overall"]["labelled"] == 15
    assert result["injection_check"] == {
        "email": "s1_injection", "ran": True, "verified_fields": 0, "verified": [], "passed": True,
    }
    assert result["labels_verified_by"] == "Nalin (hand-checked at N1)"
    assert result["note"] == "seed emails are also the development set"


def test_wrong_verified_value_is_a_silent_error():
    def liar(email, case):
        offer = oracle(email, case)
        if email.message_id == LABELS["s2_offer"]["message_id"]:
            offer.unit_price = offer.unit_price.model_copy(update={"value": 19.0})
        return offer

    result = seed_eval.run(liar)
    assert result["overall"]["silent_errors"] == 1
    assert result["silent_errors"][0]["email"] == "s2_offer"
    assert result["silent_errors"][0]["field"] == "unit_price"


def test_unit_mismatch_counts_as_wrong():
    def wrong_unit(email, case):
        offer = oracle(email, case)
        offer.quantity = offer.quantity.model_copy(update={"unit": "carton"})
        return offer

    result = seed_eval.run(wrong_unit)
    assert result["per_field"]["quantity"]["correct"] == 0
    assert result["per_field"]["quantity"]["silent_errors"] == 3
