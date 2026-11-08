"""La vague du jour, jamais son rappel : le premier nombre après le nom du candidat."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from mining import columns


@pytest.mark.parametrize(
    "source, name, expected",
    [
        (
            "   Jean-Luc Mélenchon                                 19                           17",
            "Jean-Luc Mélenchon",
            "19",
        ),
        ("Marine Le Pen 34 33", "Marine Le Pen", "34"),
        ("Fabien Roussel 2,5 % 2 %", "Fabien Roussel", "2.5"),
        ("Nathalie Arthaud <1 1", "Nathalie Arthaud", "0.5"),
        ("1 Marine Le Pen 35 (+1)", "Marine Le Pen", "35"),
        ("Jean-Luc MÉLENCHON 18", "Jean-Luc Mélenchon", "18"),
        ("MÉLENCHON 18", "Jean-Luc Mélenchon", "18"),
        ("Marine Le Pen", "Marine Le Pen", None),
    ],
)
def test_le_premier_nombre_apres_le_nom(source, name, expected):
    found = columns.first_number_after(source, name)
    assert found == (Decimal(expected) if expected else None)


def test_une_part_prise_au_rappel_est_signalee_une_fois():
    proposal = SimpleNamespace(
        evidence={
            "20261103_1105_hi_A": {
                "values": [
                    {"candidat": "Jean-Luc Mélenchon", "intentions": "17", "source": "Jean-Luc Mélenchon 19 17"},
                    {"candidat": "Marine Le Pen", "intentions": "34", "source": "Marine Le Pen 34 33"},
                ]
            }
        }
    )
    alerts = columns.check(proposal)
    assert len(alerts) == 1
    assert alerts[0].startswith("`20261103_1105_hi_A` · Jean-Luc Mélenchon : 17 n'est pas le premier nombre")
