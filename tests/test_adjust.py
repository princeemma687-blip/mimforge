"""Phase 4.4: the bounded auto-adjust loop fixes a seeded parameter
error, and says plainly when it cannot.
"""

from mimforge.adjust import auto_adjust

TARGET = 9.81
NOMINAL_LENGTH_M = 0.90


def _length_rule(parameters, outcome, target):
    """Recovered value scales as nominal/actual length, so multiply
    the length by outcome/target to land on the nominal length."""
    new_length = parameters["length_m"] * outcome / target
    return {"length_m": new_length}


def _evaluate_length(parameters):
    """A machine whose set length is off recovers a value off by the
    same ratio (nominal/actual)."""
    return TARGET * NOMINAL_LENGTH_M / parameters["length_m"]


def test_seeded_length_error_is_fixed_in_two_iterations():
    result = auto_adjust(
        {"length_m": 0.95},  # seeded 5 cm long
        evaluate=_evaluate_length,
        adjust=_length_rule,
        target=TARGET,
        band_percent=3.0,
        max_iterations=3,
    )
    assert result.fixed is True
    assert len(result.attempts) == 2
    assert result.attempts[0].within_tolerance is False
    assert result.attempts[1].within_tolerance is True
    assert result.final_parameters["length_m"] == 0.90 or abs(
        result.final_parameters["length_m"] - NOMINAL_LENGTH_M
    ) < 1e-9
    assert "fixed in 2 iteration" in result.message


def test_already_correct_parameters_pass_on_the_first_attempt():
    result = auto_adjust(
        {"length_m": NOMINAL_LENGTH_M},
        evaluate=_evaluate_length,
        adjust=_length_rule,
        target=TARGET,
        band_percent=3.0,
    )
    assert result.fixed is True
    assert len(result.attempts) == 1


def test_no_change_rule_is_reported_unfixable_not_passed():
    result = auto_adjust(
        {"length_m": 0.95},
        evaluate=_evaluate_length,
        adjust=lambda params, outcome, target: dict(params),  # proposes nothing
        target=TARGET,
        band_percent=3.0,
        max_iterations=3,
    )
    assert result.fixed is False
    assert len(result.attempts) == 1  # stops as soon as it sees no change
    assert "unfixable" in result.message


def test_immovable_outcome_is_reported_unfixable_after_max_iterations():
    result = auto_adjust(
        {"length_m": 0.95},
        evaluate=lambda params: 5.0,  # never moves, whatever the length
        adjust=_length_rule,
        target=TARGET,
        band_percent=3.0,
        max_iterations=3,
    )
    assert result.fixed is False
    assert len(result.attempts) == 3
    assert "unfixable after 3 iteration" in result.message
    assert "teacher review" in result.message
