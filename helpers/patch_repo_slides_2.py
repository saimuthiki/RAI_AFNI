# -*- coding: utf-8 -*-
"""Embeds specific facts from the user's pasted framework write-ups into the
existing repo slide content for the repos they cover, then re-serializes."""
import pprint
from repo_slide_content import REPO_SLIDES

by_folder = {r["repo_folder"]: r for r in REPO_SLIDES}

infosys = by_folder["Infosys-Responsible-AI-Toolkit-master"]
infosys["limitations"].append(
    "Version drift across internal modules (one service pins openai SDK 1.52.2, another 0.28.0) plus "
    "hardcoded thresholds, with no vendor SLA on the OSS repo itself."
)
infosys["prerequisites"] = infosys["prerequisites"].rstrip(".") + \
    "; Azure Blob Storage (the file-storage module is hard-wired to it)"
infosys["fit"] = (
    "Best treated as a reference architecture or a consulting-supported deployment, not a quick pip install - "
    "a strong Azure fit given its native Azure Blob Storage dependency, and the shape (not the code) to copy "
    "for AFNI's own build."
)

nemo = by_folder["Guardrails-develop"]
nemo["limitations"].append(
    "NVIDIA's enterprise NIM safety microservices (Content Safety, Topic Control, Jailbreak Detection) report "
    "0.79-0.88 F1 with +100-300ms added latency, and the self-managed OSS server has no built-in high "
    "availability - production HA needs the paid NVIDIA AI Enterprise license (about $4,500/GPU/yr list)."
)
for i, feat in enumerate(nemo["features"]):
    if "third-party moderation vendors" in feat or "vendor" in feat.lower():
        nemo["features"][i] = feat.replace("15+", "~25+")

ga = by_folder["guardrails-main"]
ga["limitations"].append(
    "The Hub and its free hosted inference are being retired on August 6, 2026, and only about 78% of "
    "validators had migrated to plain PyPI packages as of this review - a real near-term compatibility risk."
)

lg = by_folder["llm-guard-main"]
lg["features"].append(
    "Dedicated bias scanner (valurank/distilroberta-bias) and toxicity scanner (unitary/unbiased-toxic-roberta) "
    "- a fairness check most competing gateways lack"
)

header = '''# -*- coding: utf-8 -*-
"""
Plain-English slide copy for each of the 23 repositories.
Hand-written summaries (by the assistant) derived from the deep-dive reports
in RAI_Repo_Reports.json, simplified for a client-facing deck, enriched with
tier/vendor/build-vs-buy framing and specific facts cross-checked against
external framework write-ups.
"""

REPO_SLIDES = '''

with open("repo_slide_content.py", "w", encoding="utf-8") as f:
    f.write(header)
    f.write(pprint.pformat(REPO_SLIDES, width=118, sort_dicts=False))
    f.write("\n\n# Sanity check helper\nif __name__ == \"__main__\":\n"
            "    print(f\"{len(REPO_SLIDES)} repo slide entries defined\")\n"
            "    folders = [r[\"repo_folder\"] for r in REPO_SLIDES]\n"
            "    assert len(folders) == len(set(folders)), \"duplicate repo_folder!\"\n")

print("Patched specific facts into repo_slide_content.py")
