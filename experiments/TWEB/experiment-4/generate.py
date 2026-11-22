"""Build Experiment 4 supplementary material from the exported evidence in this folder.

Default compilation preserves manual TeX edits. --refresh-source explicitly rebuilds
main.tex from CSV/JSON exports and saved thumbnails. No database or services are used.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from statistics import mean

EXPERIMENT_DIR = Path(__file__).resolve().parent
CATEGORIES = ("syntactic", "semantic", "layout")
COMPONENTS = ("text_percent", "links_percent", "images_percent")
METRICS = ("axe", "lighthouse", "content_retention", "cost_usd", "seconds", "total_tokens", "evaluated_candidates", "syntactic_failures", "semantic_failures", "layout_failures")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_csv(directory, name):
    with (directory / "data" / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def latex(value):
    substitutions = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
                     "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
                     "^": r"\textasciicircum{}"}
    return "".join(substitutions.get(character, character) for character in str(value)).replace("\n", r"\newline ")


class Report:
    def __init__(self):
        self.blocks = []

    def add(self, value):
        self.blocks.append(value)

    def paragraph(self, value):
        self.add(latex(value) + "\n")

    def heading(self, value, subsection=False):
        command = "subsection" if subsection else "section"
        self.add("\\" + command + "{" + latex(value) + "}\n")

    def table(self, headers, rows, weights):
        total = sum(weights)
        columns = []
        for index, weight in enumerate(weights):
            width = f"{weight / total:.4f}\\linewidth"
            if index:
                width = "\\dimexpr" + width + "-2\\tabcolsep\\relax"
            columns.append("p{" + width + "}")
        self.add(r"\begingroup\footnotesize\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1.14}")
        self.add(r"\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}" + "".join(columns) + r"@{}}\toprule")
        self.add(" & ".join(r"\raggedright\textbf{" + latex(value) + "}" for value in headers) + r"\tabularnewline\midrule")
        for row in rows:
            self.add(" & ".join(r"\raggedright " + latex(value) for value in row) + r"\tabularnewline")
        self.add(r"\bottomrule\end{tabular*}\endgroup\par\medskip" + "\n")

    def quote(self, value):
        self.add(r"\begin{quote}\footnotesize\ttfamily\raggedright\sloppy " + latex(value) + r"\end{quote}" + "\n")

    def page(self):
        self.add(r"\clearpage")


def number(value, places=2):
    return f"{float(value):,.{places}f}"


def visual_label(value):
    return {"admitted": "Accepted", "rejected": "Not accepted"}.get(value, value)


def load_evidence(directory):
    manifest = json.loads((directory / "data/checksums.json").read_text())
    for relative, expected in manifest["files"].items():
        if digest((directory / relative).read_bytes()) != expected:
            raise ValueError("Exported evidence changed: " + relative)
    result = {name: read_csv(directory, name + ".csv") for name in (
        "runs", "sources", "iterations", "requests", "fixed-conditions", "accounting", "prompts")}
    for name in ("protocol", "decisions", "skills", "prompt-examples"):
        result[name] = json.loads((directory / "data" / (name + ".json")).read_text())
    if (directory / "data/task-accounting.csv").exists():
        result["task-accounting"] = read_csv(directory, "task-accounting.csv")
    assert len(result["runs"]) == len(result["sources"]) == 30
    assert len(result["iterations"]) == result["protocol"]["evaluated_versions"] and len(result["fixed-conditions"]) == 450
    for source in result["sources"]:
        rows = [row for row in result["fixed-conditions"] if row["domain"] == source["domain"]]
        assert len(rows) == 15 and all(row["input_sha256"] == source["input_sha256"] for row in rows)
    result["exported_files_checked"] = len(manifest["files"])
    return result


def source_mean(evidence, domain, policy, key):
    rows = evidence["runs"] if policy == "P5" else evidence["fixed-conditions"]
    values = [float(row[key]) for row in rows if row["domain"] == domain and row["policy"] == policy]
    assert len(values) == (1 if policy == "P5" else 3)
    return mean(values)


def cohort_means(evidence):
    domains = evidence["protocol"]["domains"]
    return {policy: {key: mean(source_mean(evidence, domain, policy, key) for domain in domains)
                     for key in METRICS}
            for policy in ("P0", "P1", "P2", "P3", "P4", "P5")}


def route_text(actions):
    labels = {"openai/gpt-6-luna": "L", "openai/gpt-6-luna@high": "H", "anthropic/claude-haiku-5.5": "A"}
    chunks = []
    for action, _ in groupby(actions):
        policy, worker = action.split(":", 1)
        chunks.append(policy + "/" + labels[worker])
    return " > ".join(chunks)


def write_domain(report, evidence, row):
    domain = row["domain"]
    source = next(source for source in evidence["sources"] if source["domain"] == domain)
    decisions = [item for item in evidence["decisions"] if str(item["run_id"]) == row["run_id"]]
    planner = "D" if "decisions" in row["planner_models"] else "G"
    report.add(r"\noindent\begin{minipage}{\linewidth}")
    report.heading(domain + " -- run " + row["run_id"], subsection=True)
    baseline = "Source #" + row["source"] + "; reference Axe " + source["axe"] + " / Lighthouse " + source["lighthouse"]
    if (source["axe"], source["lighthouse"]) != (source["recorded_audit_axe"], source["recorded_audit_lighthouse"]):
        baseline += "; execution baseline " + source["recorded_audit_axe"] + "/" + source["recorded_audit_lighthouse"]
    report.add(r"{\small " + latex(baseline + ".") + r"}\par\smallskip")
    report.add(r"\noindent\begin{minipage}[t]{.43\linewidth}\vspace{0pt}\centering")
    for index, item in enumerate((source, row)):
        report.add(r"\begin{minipage}[t]{.47\linewidth}\vspace{0pt}\centering\includegraphics[width=\linewidth]{" + item["thumbnail"] + r"}\par\footnotesize " + ("Original" if index == 0 else "Selected P5") + r"\end{minipage}" + (r"\hfill" if index == 0 else r"\par\smallskip"))
    report.add(r"{\footnotesize Route: " + latex(route_text(json.loads(row["actual"]))) + r"\par Planner: " + planner + "; visual: " + visual_label(row["visual_decision"]) + r".\par Usability checks: " + visual_label(row["functional_status"]) + r".}\end{minipage}\hfill\begin{minipage}[t]{.54\linewidth}\vspace{0pt}")
    p2 = lambda key: source_mean(evidence, domain, "P2", key)
    report.table(["Measure", "P2 mean", "P5"], [
        ["Axe / LH", number(p2("axe"), 1) + "/" + number(p2("lighthouse"), 1), row["axe"] + "/" + row["lighthouse"]],
        ["Syn/Sem/Lay", "/".join(number(p2(key + "_failures"), 1) for key in CATEGORIES), "/".join(row[key + "_failures"] for key in CATEGORIES)],
        ["Content %", number(p2("content_retention"), 1), number(row["content_retention"], 1)],
        ["USD", number(p2("cost_usd"), 4), number(row["cost_usd"], 4)],
        ["Time (s)", number(p2("seconds"), 1), number(row["seconds"], 1)],
        ["Tokens (K)", number(p2("total_tokens") / 1000, 1), number(float(row["total_tokens"]) / 1000, 1)],
    ], [40, 31, 29])
    report.add(r"\end{minipage}\par")
    coverage = "/".join(number(float(row[key + "_coverage"]) * 100, 1) for key in CATEGORIES)
    report.add(latex("Text/link/image retention: " + "/".join(number(row[key], 0) for key in COMPONENTS) + "%; Syn/Sem/Lay coverage: " + coverage + "%; " + str(len(decisions)) + " recorded choices.") + r"\par")
    report.add(r"\end{minipage}\par\medskip")


def write_source(evidence, directory):
    report = Report()
    runs = sorted(evidence["runs"], key=lambda row: row["domain"])
    means = cohort_means(evidence)
    total = sum(Decimal(row["cost_usd"]) for row in runs)
    report.add(r"""%% Compile directly to preserve edits. --refresh-source rebuilds from exported evidence.
\documentclass[acmsmall,screen,nonacm]{acmart}
\acmJournal{TWEB}
\setcopyright{none}
\acmDOI{}
\settopmatter{printacmref=false,printccs=false,printfolios=true}
\definecolor{HarnessBlue}{HTML}{18529D}
\renewcommand{\thesection}{S\arabic{section}}
\makeatletter
\g@addto@macro\@secfont{\Large}
\makeatother
\begin{document}
\raggedbottom
\pagestyle{plain}
\begin{titlepage}
\vspace*{12pt}
\noindent\textcolor{HarnessBlue}{\textbf{SUPPLEMENTARY MATERIAL / EXPERIMENT 4}}\par\bigskip
\noindent{\LARGE\bfseries Harness Engineering for Web Accessibility\par}
\medskip
\noindent{\Large Orchestrating Automated Remediation with Agents and LLMs\par}
\vspace{22pt}
\noindent Guillermo Vera-Amaro and José Rafael Rojano-Cáceres\par
\medskip
\noindent Facultad de Estadística e Informática\par
\noindent Universidad Veracruzana, Xalapa, Mexico\par
\vspace{24pt}
\noindent{\Large\bfseries\textcolor{HarnessBlue}{Experiment 4. Adaptive strategy and model selection}\par}
\medskip
This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection. This companion documents the thirty selected P5 executions used to examine adaptive strategy and repair-model selection. It connects their saved pages, executed routes, measured accessibility and preservation, planning evidence, and complete execution resources.\par\bigskip
\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lll@{}}\toprule
\textbf{30} frozen sources & \textbf{30} adaptive runs & \textbf{EVALUATEDVERSIONS} evaluated versions\\\bottomrule
\end{tabular*}\par\bigskip
RETENTIONOVERVIEW The executed routes can change strategy or worker as measurements accumulate. Accessibility, preservation, and complete resource demand are compared with the 450 fixed P0--P4 conditions on the same sources. The planner uses the current page, its measured findings, and feedback from the same execution to choose each action.
\end{titlepage}
""")
    report.blocks = [line.replace("EVALUATEDVERSIONS", str(len(evidence["iterations"]))) for line in report.blocks]
    retained_all = all(float(row[key]) == 100 for row in runs for key in COMPONENTS)
    overview = ("All thirty selected outputs retain the measured source text, links, and images."
                if retained_all else "The selected outputs have mean content retention of "
                + number(means["P5"]["content_retention"], 1) + r"\%.")
    report.blocks = [line.replace("RETENTIONOVERVIEW", overview) for line in report.blocks]
    report.heading("Source-matched comparison")
    report.table(["Policy", "Outputs", "Axe/LH", "Syn/Sem/Lay failures", "Content %", "USD", "Time min", "Tokens K"], [
        [policy, "30" if policy == "P5" else "90", number(values["axe"], 2) + "/" + number(values["lighthouse"], 1),
         "/".join(number(values[key + "_failures"], 2) for key in CATEGORIES), number(values["content_retention"], 1),
         number(values["cost_usd"], 4), number(values["seconds"] / 60, 2), number(values["total_tokens"] / 1000, 1)]
        for policy, values in means.items()], [9, 10, 16, 23, 11, 11, 11, 12])
    report.paragraph("Values are means per source. P0--P4 first average the three fixed repair configurations within each source; P5 contributes one selected execution. Syn/Sem/Lay denotes syntactic, semantic, and layout failures. Content retention averages text, link-destination, and image-reference retention. Missing or unassessed checks are not passes.")
    report.paragraph("P5 has mean Axe " + number(means["P5"]["axe"], 2) + " and semantic failures " + number(means["P5"]["semantic_failures"], 2) + ", compared with " + number(means["P2"]["axe"], 2) + " and " + number(means["P2"]["semantic_failures"], 2) + " for P2 averaged across configurations. The table relates these correction and preservation outcomes to complete workflow resources. The thirty adaptive executions cost US$" + number(total) + ".")
    coverage = {policy: "/".join(number(100 * mean(source_mean(evidence, domain, policy, category + "_coverage")
                                                  for domain in evidence["protocol"]["domains"]), 1)
                                for category in CATEGORIES)
                for policy in ("P2", "P5")}
    report.paragraph("Mean syntactic/semantic/layout assessment coverage is " + coverage["P5"] + "% for P5 and " + coverage["P2"] + "% for P2. Coverage measures the proportion of applicable checks with conclusive judgments. Checks lacking such judgments do not count as confirmed corrections.")
    visual_admissions = sum(row["visual_decision"] == "admitted" for row in runs)
    functional_flags = sum(row["functional_status"] == "rejected" for row in runs)
    report.paragraph(str(visual_admissions) + " selected outputs are visually accepted. Separate recorded usability checks flag " + str(functional_flags) + " outputs. The source panels show both judgments; runs.csv preserves the usability reasons separately from the visual rationale.")
    report.paragraph("Reference audits provide the common source baseline for strategy comparisons. Execution audits are also preserved in sources.csv; a differing execution baseline is identified in its source panel.")
    initial = [json.loads(row["actual"])[0] for row in runs]
    report.heading("Recorded routes", subsection=True)
    changed_policy = sum(len({action.split(":",1)[0] for action in json.loads(row["actual"])}) > 1 for row in runs)
    changed_worker = sum(len({action.split(":",1)[1] for action in json.loads(row["actual"])}) > 1 for row in runs)
    initial_counts = [policy + " on " + str(count) + " sources"
                      for policy in ("P1", "P2", "P3", "P4")
                      if (count := sum(action.startswith(policy + ":") for action in initial))]
    report.paragraph("The first evaluated repairs use " + ", ".join(initial_counts) + ". " + str(changed_policy) + " sources change strategy and " + str(changed_worker) + " change worker among evaluated versions. Decisions and measured page versions remain distinct in the evidence files.")
    report.paragraph("The following source panels compare P5 with source-matched P2 means. L denotes GPT-Luna 6 light, H denotes GPT-Luna 6 high, and A denotes Haiku 5.5 light. Routes list actions producing evaluated versions; > marks a change of action. Planner D denotes GPT-Luna 6 Decisions, and G denotes GPT-Luna 6. The exact model configurations and requests remain recorded per execution.")
    report.page()
    report.heading("Recorded adaptive prompts and evidence")
    examples = evidence["prompt-examples"]
    planner = examples["planner"]
    question = json.loads(next(part["text"] for part in planner["parts"] if part["role"] == "decision_schema"))
    report.heading("Strategy and worker selection", subsection=True)
    action = question["action"] if isinstance(question, dict) else next(item for item in question if item["name"] == "action")
    report.quote(action["instructions"])
    report.paragraph("Recorded GPT-Luna 6 Decisions request " + planner["call_id"] + " (run " + str(planner["run_id"]) + "). Allowed choices identify the strategy and worker. The input combines the current page profile, findings, retention, coverage, within-run feedback, and remaining resources. The complete instruction remains in prompt-examples.json and the exported request instructions.")
    report.heading("Repair request under the selected contract", subsection=True)
    patch = examples["patch"]
    text = patch["parts"][0]["text"]
    instruction = next(line for line in text.splitlines() if line.startswith("Intervention:"))
    report.quote(text.split("Patch prompt version:")[0].strip() + "\n" + instruction)
    report.paragraph("Recorded repair request " + patch["call_id"] + " (run " + str(patch["run_id"]) + "). The controller supplies the selected scope, current document context, measured findings, component evidence, and versioned skills. Responses propose operations. The deterministic controller validates and applies them.")
    report.page()
    report.heading("Skills, tools, and task contracts")
    report.table(["Task / tool", "Input and output contract"], [
        ["Route planning", "Choose from the recorded allowed strategy/worker alternatives, recommend the next action or stopping, and retain the closed choice."],
        ["plan_components / diagnosis", "Group supported causes and dependencies, or interpret unresolved findings before local generation."],
        ["apply_constrained_patch", "Validate selectors, operation permissions, protected content, native controls, and component dependencies before applying changes."],
        ["evaluate_candidate / measure_content_retention", "Record audits, taxonomic findings and coverage, source inventories, captures, and independent visual evidence."],
        ["select_best_candidate", "Retain the measured endpoint using target distance, audit criteria, preservation and applicable contextual evidence."],
    ], [35, 65])
    report.table(["Versioned skill", "Recorded instruction"], [[skill["id"] + " @ " + skill["version"], skill["instruction"]] for skill in evidence["skills"]], [36, 64])
    if "rag" in examples:
        report.heading("ACT RAG supplied to generation", subsection=True)
        rag = examples["rag"]["text"].replace("\\n", "\n")
        report.quote(re.split(r"Code example:", rag, maxsplit=1, flags=re.I)[0].strip())
        report.paragraph("This excerpt belongs to repair request " + examples["rag"]["call_id"] + ". rag.json records the ACT corpus, query hash and injected case identities and the exact repair request that received them.")
    report.paragraph("The controller invokes execution tools, validates advice, enforces recorded attempt/time/charge limits, and records every response. A plan is not evidence that its steps were executed. Visual acceptance remains separate from technical validity, audit targets and endpoint selection.")
    protocol = next(iter(evidence["protocol"]["recorded_runs"].values()))
    if protocol.get("iteration_policy") == "evaluated-candidates-v1":
        report.paragraph("The limit is " + str(protocol["max_iterations"]) + " evaluated candidates, with up to "
                         + str(protocol["max_generation_attempts_per_candidate"])
                         + " generation attempts per candidate. The controller ends generation at Axe 0 and Lighthouse 100 and completes the final taxonomy assessment. Complementary findings remain separate from these audit targets. Recorded monetary and time limits bound further execution.")
    for offset in range(0, len(runs), 3):
        report.page()
        report.heading("Source evidence -- " + str(offset + 1) + " to " + str(min(offset + 3, len(runs))))
        for row in runs[offset:offset + 3]:
            write_domain(report, evidence, row)
    report.page()
    report.heading("Resources, accounting, and traceability")
    groups = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cost": Decimal("0")})
    if "task-accounting" in evidence:
        for task in evidence["task-accounting"]:
            groups[task["role"]] = {"calls": int(task["calls"]),
                                    "input": int(task["input_tokens"]),
                                    "output": int(task["output_tokens"]),
                                    "cost": Decimal(task["cost_usd"])}
    else:
        for call in evidence["requests"]:
            if call["in_analysis"] != "True":
                continue
            group = groups[call["role"]]
            group["calls"] += 1
            group["input"] += int(call["input_tokens"] or 0)
            group["output"] += int(call["output_tokens"] or 0)
            group["cost"] += Decimal(call["cost_usd"])
    report.table(["Recorded task", "Calls", "Input tokens", "Output tokens", "USD"], [
        [role, values["calls"], number(values["input"], 0), number(values["output"], 0), number(values["cost"], 6)]
        for role, values in sorted(groups.items())], [30, 10, 22, 22, 16])
    operational = sum(values["cost"] for values in groups.values())
    assert abs(operational - total) < Decimal("0.000001")
    report.paragraph("Execution costs cover every planning, generation and assessment request in the thirty selected executions, totaling US$" + number(total, 6) + ". accounting.csv links each run's cost to its recorded call charges and operational duration. Time is measured in seconds for the complete workflow; provider-request durations are recorded separately.")
    report.heading("Evidence map", subsection=True)
    report.paragraph("runs.csv and sources.csv bind the selected outputs and captures to exact frozen inputs. iterations.csv preserves evaluated versions for traceability. decisions.json records the closed choices, while prompts.csv links completed planning and repair requests. task-accounting.csv preserves complete task resources. The 450 source-matched fixed endpoints remain in fixed-conditions.csv.")
    report.paragraph("The source panels report the selected outputs. Visual rationales, source hashes, model settings and request/response identities link these results to their supporting evidence. Rebuilding this report reads those files without running models, acquiring pages, or altering reviews.")
    report.add(r"\end{document}")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "main.tex").write_text("\n".join(report.blocks) + "\n")
    return {"runs": 30, "sources": 30, "evaluated_versions": len(evidence["iterations"]), "fixed_conditions": 450,
            "recorded_calls": len(evidence["requests"]), "decisions": len(evidence["decisions"]),
            "published_cost_usd": str(total), "exported_files_checked": evidence["exported_files_checked"]}


def compile_pdf(directory, output):
    with tempfile.TemporaryDirectory(prefix="supp-e4-latex-") as temporary:
        build = Path(temporary)
        command = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-outdir=" + str(build), "main.tex"]
        process = subprocess.run(command, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if process.returncode:
            raise RuntimeError(process.stdout[-10000:])
        log = (build / "main.log").read_text(errors="replace")
        warnings = [line for line in log.splitlines() if "Overfull" in line or "undefined" in line]
        output.parent.mkdir(parents=True, exist_ok=True)
        staged = output.with_suffix(".publishing.pdf")
        shutil.copyfile(build / "main.pdf", staged)
        staged.replace(output)
    from pypdf import PdfReader
    reader = PdfReader(output)
    return {"pages": len(reader.pages), "bytes": output.stat().st_size, "pdf_sha256": digest(output.read_bytes()),
            "tex_sha256": digest((directory / "main.tex").read_bytes()),
            "class_sha256": digest((directory / "acmart.cls").read_bytes()), "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EXPERIMENT_DIR / "supplementary.pdf")
    parser.add_argument("--refresh-source", action="store_true", help="Explicitly rebuild main.tex from exported evidence.")
    parser.add_argument("--receipt", type=Path, help="Optional external verification receipt.")
    args = parser.parse_args()
    result = {}
    if args.refresh_source:
        result.update(write_source(load_evidence(EXPERIMENT_DIR), EXPERIMENT_DIR))
    elif not (EXPERIMENT_DIR / "main.tex").exists():
        parser.error("Run with --refresh-source to create main.tex.")
    result.update(compile_pdf(EXPERIMENT_DIR, args.output.resolve()))
    result.update(output=str(args.output.resolve()), source_dir=str(EXPERIMENT_DIR), source_regenerated=args.refresh_source)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
