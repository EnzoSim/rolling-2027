"""La reprise de Mieux Voter n'importe que les sondages que nous n'avons pas."""

import csv
from pathlib import Path

import pytest

import merge
from scripts.import_upstream import Table, classify, import_tables, main, read_csv, read_tables, safe_text

POLL_HEADER = "poll_id,hypothese,nom_institut,commanditaire,debut_enquete,fin_enquete,echantillon,filename"
LE_PEN = "Marine Le Pen"
ATTAL = "Gabriel Attal"
PHILIPPE = "Édouard Philippe"
LISNARD = "David Lisnard"


def write_repo(root, hypotheses, polls, candidates=(LE_PEN, ATTAL, PHILIPPE)):
    """`hypotheses` : {id: [noms]}. `polls` : {poll_id: (hypothèse, institut, début, fin, {nom: part})}."""
    (root / "polls").mkdir(parents=True)
    with (root / "candidats.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["candidate_id", "complete_name", "name", "surname", "parti"])
        for name in candidates:
            first, last = name.split(" ", 1)
            writer.writerow([(first[0] + last[0]).upper(), name, first, last, ""])
    with (root / "hypotheses.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["id_hypothese", "hypothese_complete", "commentaire"])
        for hypothesis, names in hypotheses.items():
            writer.writerow([hypothesis, ",".join(names) + ",", ""])
    with (root / "polls.csv").open("w", encoding="utf-8", newline="") as f:
        f.write(POLL_HEADER + "\n")
        writer = csv.writer(f, lineterminator="\n")
        for poll_id, (hypothesis, institute, start, end, _) in polls.items():
            writer.writerow([poll_id, hypothesis, institute, "LCI", start, end, 1000, "notice.pdf"])
    for poll_id, (*_, shares) in polls.items():
        lines = ["candidat,intentions,erreur_sup,erreur_inf"]
        lines += [f"{name},{share},1.0,-1.0" for name, share in shares.items()]
        (root / "polls" / f"{poll_id}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


@pytest.fixture
def repos(tmp_path):
    def build(ours, theirs):
        return write_repo(tmp_path / "ours", *ours), write_repo(tmp_path / "theirs", *theirs)

    return build


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def plan_of(ours, theirs):
    return classify(read_tables(ours), read_tables(theirs))


def test_opinionway_with_other_letters_is_the_same_poll(repos):
    # Le 13 et 14 octobre 2026 : notre A est leur B, notre B est leur A.
    dates = ("OpinionWay", "2026-10-13", "2026-10-14")
    wide = {LE_PEN: 35, ATTAL: 5, PHILIPPE: 12}
    narrow = {LE_PEN: 37, ATTAL: 11}
    ours, theirs = repos(
        (
            {"H91": [LE_PEN, ATTAL, PHILIPPE], "H67": [LE_PEN, ATTAL]},
            {"20261013_1014_ow_A": ("H91", *dates, wide), "20261013_1014_ow_B": ("H67", *dates, narrow)},
        ),
        (
            {"H9": [LE_PEN, ATTAL, PHILIPPE], "H6": [LE_PEN, ATTAL]},
            {"20261013_1014_ow_A": ("H6", *dates, narrow), "20261013_1014_ow_B": ("H9", *dates, wide)},
        ),
    )
    plan = plan_of(ours, theirs)
    assert (plan.known, plan.new, plan.diverging) == (2, [], [])


def test_only_the_margins_differ_on_yougov(repos):
    poll = ("H1", "YouGov", "2026-10-12", "2026-10-15", {LE_PEN: 52, PHILIPPE: 48})
    ours, theirs = repos(
        ({"H1": [LE_PEN, PHILIPPE]}, {"20261012_1015_yg_2A": poll}),
        ({"H1": [LE_PEN, PHILIPPE]}, {"20261012_1015_yg_2A": poll}),
    )
    their_file = theirs / "polls/20261012_1015_yg_2A.csv"
    their_file.write_text(their_file.read_text().replace("1.0,-1.0", "3.96,-3.96"))
    plan = plan_of(ours, theirs)
    assert (plan.known, plan.new, plan.diverging) == (1, [], [])


def test_the_same_shares_under_another_spelling_are_not_imported_twice(repos):
    shares = {LE_PEN: 36, ATTAL: 14}
    ours, theirs = repos(
        (
            {"H1": [LE_PEN, ATTAL]},
            {"20261020_1021_hi_A": ("H1", "Harris Interactive", "2026-10-20", "2026-10-21", shares)},
        ),
        ({"H1": [LE_PEN, ATTAL]}, {"20261020_1021_ti_A": ("H1", "Toluna Harris", "2026-10-20", "2026-10-21", shares)}),
    )
    assert plan_of(ours, theirs).new == []


def test_other_shares_for_the_same_poll_keep_ours_and_warn(repos, capsys, tmp_path):
    dates = ("IFOP", "2026-10-27", "2026-10-29")
    ours, theirs = repos(
        ({"H125": [LE_PEN, ATTAL]}, {"20261027_1029_if_A": ("H125", *dates, {LE_PEN: 36, ATTAL: 14})}),
        ({"H116": [LE_PEN, ATTAL]}, {"20261027_1029_if_A": ("H116", *dates, {LE_PEN: 37, ATTAL: 13})}),
    )
    before = (ours / "polls/20261027_1029_if_A.csv").read_bytes()
    assert main([str(theirs), "--root", str(ours)]) == 0
    assert "::warning::Parts différentes de l'amont" in capsys.readouterr().out
    assert (ours / "polls/20261027_1029_if_A.csv").read_bytes() == before


def test_an_absent_poll_lands_on_our_hypothesis_of_the_same_list(repos):
    poll = ("H116", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 35, ATTAL: 15})
    ours, theirs = repos(
        ({"H125": [ATTAL, LE_PEN]}, {}),
        ({"H116": [LE_PEN, ATTAL]}, {"20261103_1104_el_A": poll}),
    )
    assert main([str(theirs), "--root", str(ours)]) == 0
    assert [row["hypothese"] for row in read_csv(ours / "polls.csv")] == ["H125"]
    assert [row["id_hypothese"] for row in read_csv(ours / "hypotheses.csv")] == ["H125"]
    assert (ours / "polls/20261103_1104_el_A.csv").read_text() == (theirs / "polls/20261103_1104_el_A.csv").read_text()
    assert len(merge.merge(ours)) == 2


def test_a_new_list_takes_our_next_number_never_theirs(repos):
    first = ("H5", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 60, ATTAL: 40})
    second = ("H2_7", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 55, PHILIPPE: 45})
    ours, theirs = repos(
        ({"H125": [LE_PEN], "H124": [ATTAL], "H2_12": [ATTAL, PHILIPPE]}, {}),
        (
            {"H5": [LE_PEN, ATTAL], "H2_7": [LE_PEN, PHILIPPE]},
            {"20261103_1104_el_A": first, "20261103_1104_el_2A": second},
        ),
    )
    assert main([str(theirs), "--root", str(ours)]) == 0
    assert [row["hypothese"] for row in read_csv(ours / "polls.csv")] == ["H126", "H2_13"]
    assert [row["id_hypothese"] for row in read_csv(ours / "hypotheses.csv")][-2:] == ["H126", "H2_13"]
    assert len(merge.merge(ours)) == 4


def test_a_candidate_only_upstream_knows_comes_with_the_poll(repos):
    poll = ("H1", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 70, LISNARD: 30})
    ours, theirs = repos(
        ({}, {}),
        ({"H1": [LE_PEN, LISNARD]}, {"20261103_1104_el_A": poll}, (LE_PEN, LISNARD)),
    )
    assert main([str(theirs), "--root", str(ours)]) == 0
    assert LISNARD in [row["complete_name"] for row in read_csv(ours / "candidats.csv")]
    assert len(merge.merge(ours)) == 2


def test_a_candidate_id_taken_by_someone_else_stops_the_import(repos):
    poll = ("H1", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 60, "Gaël Attal": 40})
    ours, theirs = repos(
        ({}, {}),
        ({"H1": [LE_PEN, "Gaël Attal"]}, {"20261103_1104_el_A": poll}, (LE_PEN, "Gaël Attal")),
    )
    tables = read_tables(theirs)
    with pytest.raises(ValueError, match="Candidat GA"):
        import_tables(ours, theirs, tables)
    assert read_csv(ours / "polls.csv") == []


def test_a_poll_id_already_used_here_stops_the_import(repos):
    ours, theirs = repos(
        (
            {"H1": [LE_PEN, ATTAL]},
            {"20261103_1104_el_A": ("H1", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 60, ATTAL: 40})},
        ),
        (
            {"H1": [LE_PEN, ATTAL]},
            {"20261103_1104_el_A": ("H1", "Verian", "2026-11-01", "2026-11-02", {LE_PEN: 55, ATTAL: 45})},
        ),
    )
    with pytest.raises(ValueError, match="existe déjà"):
        import_tables(ours, theirs, read_tables(theirs))


def test_a_second_run_finds_nothing_and_a_dry_run_writes_nothing(repos, monkeypatch, tmp_path):
    poll = ("H1", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 60, ATTAL: 40})
    ours, theirs = repos(
        ({"H1": [LE_PEN, ATTAL]}, {}),
        ({"H1": [LE_PEN, ATTAL]}, {"20261103_1104_el_A": poll}),
    )
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    before = (ours / "polls.csv").read_bytes()

    assert main([str(theirs), "--root", str(ours), "--dry-run"]) == 0
    assert (ours / "polls.csv").read_bytes() == before
    assert output.read_text() == "changed=false\n"

    assert main([str(theirs), "--root", str(ours)]) == 0
    assert main([str(theirs), "--root", str(ours)]) == 0
    assert output.read_text() == "changed=false\nchanged=true\nchanged=false\n"
    assert len(read_csv(ours / "polls.csv")) == 1


def hostile(repos, *, mutate=None):
    """Un amont avec un sondage absent de chez nous, à abîmer."""
    poll = ("H1", "ELABE", "2026-11-03", "2026-11-04", {LE_PEN: 60, ATTAL: 40})
    ours, theirs = repos(
        ({"H1": [LE_PEN, ATTAL]}, {}),
        ({"H1": [LE_PEN, ATTAL]}, {"20261103_1104_el_A": poll}),
    )
    if mutate:
        mutate(theirs)
    return ours, theirs


def snapshot(root):
    return {path: path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_an_id_that_leaves_polls_is_refused_before_any_read(repos, tmp_path):
    def mutate(theirs):
        edit(theirs / "polls.csv", "20261103_1104_el_A", "../../ours/polls")

    ours, theirs = hostile(repos, mutate=mutate)
    before = snapshot(ours)
    with pytest.raises(ValueError, match="Identifiant de sondage refusé"):
        main([str(theirs), "--root", str(ours)])
    assert snapshot(ours) == before


def test_a_symbolic_link_in_polls_is_refused(repos, tmp_path):
    secret = tmp_path / "config"
    secret.write_text("candidat,intentions,erreur_sup,erreur_inf\nMarine Le Pen,60,1,-1\nGabriel Attal,40,1,-1\n")

    def mutate(theirs):
        path = theirs / "polls/20261103_1104_el_A.csv"
        path.unlink()
        path.symlink_to(secret)

    ours, theirs = hostile(repos, mutate=mutate)
    before = snapshot(ours)
    with pytest.raises(ValueError, match="lien symbolique"):
        main([str(theirs), "--root", str(ours)])
    assert snapshot(ours) == before


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda t: edit(t / "polls.csv", ",LCI,", ",=HYPERLINK(1),"), "valeur refusée"),
        (lambda t: edit(t / "polls.csv", ",ELABE,", ',"ELABE\n::add-mask::x",'), "valeur refusée"),
        (lambda t: edit(t / "polls.csv", "2026-11-03", "3 novembre"), "dates refusées"),
        (lambda t: edit(t / "polls.csv", ",1000,", ",mille,"), "échantillon refusé"),
        (lambda t: edit(t / "polls/20261103_1104_el_A.csv", "60,1.0", "160,1.0"), "hors de 0 à 100"),
        (lambda t: edit(t / "polls/20261103_1104_el_A.csv", "60,1.0", "60,=1+1"), "chiffre refusé"),
        (lambda t: edit(t / "polls/20261103_1104_el_A.csv", "erreur_inf", "erreur_inf,pirate"), "colonnes refusées"),
    ],
)
def test_a_hostile_value_stops_the_import_before_any_write(repos, mutate, reason):
    ours, theirs = hostile(repos, mutate=mutate)
    before = snapshot(ours)
    with pytest.raises(ValueError, match=reason):
        main([str(theirs), "--root", str(ours)])
    assert snapshot(ours) == before


def test_a_file_left_in_polls_is_never_overwritten(repos, tmp_path):
    ours, theirs = hostile(repos)
    left = ours / "polls/20261103_1104_el_A.csv"
    left.write_text("à nous\n")
    with pytest.raises(ValueError, match="existe déjà"):
        main([str(theirs), "--root", str(ours)])
    assert left.read_text() == "à nous\n"


def test_upstream_text_cannot_write_a_workflow_command():
    row = {
        "poll_id": "20261103_1104_el_A",
        "nom_institut": "ELABE\n::error::faux",
        "debut_enquete": "2026-11-03",
        "fin_enquete": "2026-11-04",
    }
    label = Table(row, {}).label()
    assert "\n" not in label and "::" not in label
    assert safe_text("a\r\n::add-mask::b") == "a : :add-mask: :b"


def test_the_workflow_imports_and_never_merges_upstream():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/sync-upstream.yml").read_text()
    assert "python scripts/import_upstream.py" in workflow
    assert "git merge" not in workflow.replace("Pas de `git merge`", "")
    assert "steps.merge" not in workflow
