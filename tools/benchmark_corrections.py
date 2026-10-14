"""Apply cited editorial edits to new isolated drafts; preserve benchmark originals."""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark import corpus, save, sha
from library import Library


def apply(folder, edits_path, output):
    folder, output = Path(folder), Path(output)
    if output.exists():
        raise ValueError("Corrected drafts must have a new destination.")
    _, sources = corpus()
    results = json.loads((folder / "results.json").read_text("utf-8"))
    by_trial = {t["trial"]: t for t in results["trials"]}
    plan = json.loads(Path(edits_path).read_text("utf-8"))
    output.mkdir(parents=True)
    summary = {
        "kind": "cited_editorial_corrections",
        "approval": "not_approved",
        "input_results_sha256": sha((folder / "results.json").read_bytes()),
        "new_inference_calls": 0,
        "quality_after_correction": "not_rechecked; no further automatic review pass",
        "drafts": [],
    }
    for item in plan["drafts"]:
        trial = by_trial[item["trial"]]
        original = folder / ("trial-%03d" % trial["trial"])
        text = (original / "translation.txt").read_text("utf-8")
        if (
            sha(text.encode()) != trial["translation_sha256"]
            or sha(sources[trial["source"]].encode()) != trial["source_sha256"]
        ):
            raise ValueError("Original text changed before editing.")
        for edit in item["edits"]:
            if (
                edit["source_quote"] not in sources[trial["source"]]
                or text.count(edit["before"]) != 1
            ):
                raise ValueError(
                    "An edit is not uniquely anchored in its exact source/translation."
                )
            if not edit["after"].strip() or edit["before"] == edit["after"]:
                raise ValueError("Empty or unchanged correction.")
            text = text.replace(edit["before"], edit["after"], 1)
        destination = output / original.name
        destination.mkdir()
        shutil.copytree(original / "library", destination / "library")
        lib = Library(destination / "library")
        try:
            with lib.pair(trial["series"], trial["source"], trial["target"]) as pair:
                prepared = pair.prepare(1)
                context = json.loads((Path(prepared["folder"]) / "context.json").read_text("utf-8"))
                template = json.loads(
                    (Path(prepared["folder"]) / "response.template.json").read_text("utf-8")
                )
                if len(context["segments"]) != 1:
                    raise ValueError("Expected the original full-preamble segment.")
                candidate = {
                    **template,
                    "segments": [{"id": context["segments"][0]["id"], "text": text}],
                }
                saved = pair.submit(1, candidate, expected_hash=pair.chapter(1)["translation_hash"])
                save(destination / "response.json", candidate)
                save(destination / "edits.json", item)
                (destination / "translation.txt").write_text(text, encoding="utf-8")
                summary["drafts"].append(
                    {
                        "trial": trial["trial"],
                        "model_of_original": trial["model"],
                        "effort_of_original": trial["effort"],
                        "source": trial["source"],
                        "target": trial["target"],
                        "original_sha256": trial["translation_sha256"],
                        "corrected_sha256": sha(text.encode()),
                        "saved": saved,
                        "edit_count": len(item["edits"]),
                        "remaining_uncertainties": item.get("remaining_uncertainties", []),
                    }
                )
        finally:
            lib.close()
    save(output / "corrections.json", summary)
    print("Separate corrected drafts:", len(summary["drafts"]), "New inference calls: 0")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("edits", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    apply(args.folder, args.edits, args.output)
