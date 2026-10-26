#!/usr/bin/env python3
"""rolling-2027 : fusionner les PR de dépouillement vérifiées restées ouvertes.

Un dépouillement complet et sans alerte s'ouvre prêt et se fusionne seul
(mining/pull_request.py). Si GitHub tombe au mauvais moment (un 502 sur « gh pr merge »,
rolling-2027#69, 26 octobre 2026), la PR reste ouverte malgré les nouveaux essais : ce
script, lancé chaque heure par retry-mining.yml, la fusionne puis relance post-merge.yml
une fois. Il ne touche ni à une PR en brouillon, ni à une PR marquée needs-human-review,
ni à une PR en conflit. « 0 » dans ROLLING_AUTOMERGE coupe tout, comme pour le reste.

    python merge_verified_prs.py --repo EnzoSim/rolling-2027
"""

import argparse
import os
import sys
from pathlib import Path

from mining import pull_request


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fusionne les PR de dépouillement vérifiées restées ouvertes.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name")
    args = parser.parse_args(argv)
    if os.environ.get("ROLLING_AUTOMERGE", "1") != "1":
        print("Fusion automatique coupée (ROLLING_AUTOMERGE) : rien à rattraper.")
        return 0
    if not args.repo:
        print("::error::Dépôt inconnu : --repo ou GITHUB_REPOSITORY.")
        return 2
    try:
        merged, failures = pull_request.catch_up(args.repo, Path(__file__).resolve().parent)
    except pull_request.PullRequestError as exc:
        print(f"::error::Rattrapage impossible : {exc}")
        return 1
    for number in merged:
        print(f"PR #{number} fusionnée.")
    for number, reason in failures:
        print(f"::warning::PR #{number} toujours ouverte : {reason}")
    if not merged and not failures:
        print("Aucune PR vérifiée en attente.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
