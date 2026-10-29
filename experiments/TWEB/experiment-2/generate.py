"""Build Experiment 2 supplementary material from its exported CSV/JSON evidence.

Default compilation preserves manual TeX edits. --refresh-source explicitly
regenerates main.tex. No database, live page or model API is used by this builder.
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
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

EXPERIMENT_DIR = Path(__file__).resolve().parent
POLICIES = ("P0", "P1", "P2", "P3", "P4")
PROFILES = ("luna-light", "luna-high", "haiku-low")
PROFILE_LABELS = {"luna-light": "L", "luna-high": "H", "haiku-low": "A"}
CATEGORIES = ("syntactic", "semantic", "layout")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_csv(directory, name):
    with (directory / "data" / (name + ".csv")).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def latex(value):
    substitutions = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
                     "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
                     "^": r"\textasciicircum{}"}
    return "".join(substitutions.get(character, character) for character in str(value)).replace("\n", r"\newline ")


def number(value, places=2):
    return f"{float(value):,.{places}f}"


def p_value(value):
    return "< .001" if value < .001 else f"{value:.3f}"


class Report:
    def __init__(self):
        self.blocks = []

    def add(self, value):
        self.blocks.append(value)

    def paragraph(self, value):
        self.add(latex(value) + "\n")

    def heading(self, value, subsection=False):
        self.add((r"\subsection{" if subsection else r"\section{") + latex(value) + "}\n")

    def table(self, headers, rows, weights):
        columns = []
        for index, weight in enumerate(weights):
            width = f"{weight / sum(weights):.4f}\\linewidth"
            if index:
                width = r"\dimexpr" + width + r"-2\tabcolsep\relax"
            columns.append("p{" + width + "}")
        self.add(r"\begingroup\footnotesize\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1.14}")
        self.add(r"\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}" + "".join(columns) + r"@{}}\toprule")
        self.add(" & ".join(r"\raggedright\textbf{" + latex(value) + "}" for value in headers) + r"\tabularnewline\midrule")
        for row in rows:
            self.add(" & ".join(r"\raggedright " + latex(value) for value in row) + r"\tabularnewline")
        self.add(r"\bottomrule\end{tabular*}\endgroup\par\medskip")

    def quote(self, value):
        self.add(r"\begin{quote}\footnotesize\ttfamily\raggedright\sloppy " + latex(value) + r"\end{quote}")

    def page(self):
        self.add(r"\clearpage")


def load_evidence(directory):
    manifest = json.loads((directory / "data/checksums.json").read_text())
    for relative, expected in manifest["files"].items():
        if digest((directory / relative).read_bytes()) != expected:
            raise ValueError("Exported evidence changed: " + relative)
    evidence = {name: read_csv(directory, name) for name in (
        "sources", "runs", "iterations", "requests", "prompts", "accounting")}
    for name in ("protocol", "skills", "prompt-examples", "paired-statistics"):
        evidence[name] = json.loads((directory / "data" / (name + ".json")).read_text())
    assert len(evidence["sources"]) == 30 and len(evidence["runs"]) == 450
    assert len(evidence["iterations"]) == 1074
    assert Counter(row["run_id"] for row in evidence["iterations"] if row["chosen"] == "True") == Counter({row["run_id"]: 1 for row in evidence["runs"]})
    for source in evidence["sources"]:
        rows = [row for row in evidence["runs"] if row["domain"] == source["domain"]]
        assert len(rows) == 15 and all(row["input_sha256"] == source["input_sha256"] for row in rows)
        assert {(row["policy"], row["profile"]) for row in rows} == {(p, w) for p in POLICIES for w in PROFILES}
    evidence["exported_files_checked"] = len(manifest["files"])
    return evidence


def example_text(example):
    return next(part["text"] for part in example["parts"] if part.get("text"))


def write_domain(report, evidence, source):
    report.page()
    report.heading(source["domain"])
    report.add(r"\noindent\begin{minipage}[t]{.16\linewidth}\vspace{0pt}\includegraphics[width=50pt]{" + source["thumbnail"] + r"}\end{minipage}\hfill\begin{minipage}[t]{.81\linewidth}\vspace{0pt}")
    report.paragraph("Frozen source #" + source["source"] + ". Original Axe " + source["axe"] + " / Lighthouse " + source["lighthouse"] + ".")
    report.add(r"{\footnotesize " + latex("L = GPT-Luna 6 light; H = GPT-Luna 6 high; A = Haiku 5.5 light. R = content retention. V = automatic visual judgment: Y accepted, N not accepted.") + r"}\end{minipage}\par\medskip")
    weights = (5, 5, 6, 10, 11, 12, 8, 9, 9, 10, 5)
    columns = []
    for index, weight in enumerate(weights):
        width = f"{weight / sum(weights):.4f}\\linewidth"
        if index:
            width = r"\dimexpr" + width + r"-2\tabcolsep\relax"
        columns.append("p{" + width + "}")
    report.add(r"\begingroup\footnotesize\setlength{\tabcolsep}{2pt}\renewcommand{\arraystretch}{1.0}")
    report.add(r"\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}" + "".join(columns) + r"@{}}\toprule")
    report.add(" & ".join(r"\raggedright\textbf{" + latex(value) + "}" for value in (
        "P", "LLM", "Run", "Output", "Axe/LH", "Syn/Sem/Lay", "R %", "USD", "Time s", "Tokens K", "V")) + r"\tabularnewline\midrule")
    rows = [row for row in evidence["runs"] if row["domain"] == source["domain"]]
    for index, row in enumerate(rows):
        if index and rows[index - 1]["policy"] != row["policy"]:
            report.add(r"\addlinespace[3pt]")
        cells = [row["policy"], PROFILE_LABELS[row["profile"]], row["run_id"], None,
                 row["axe"] + "/" + row["lighthouse"], "/".join(row[key + "_failures"] for key in CATEGORIES),
                 number(row["content_retention"], 1), number(row["cost_usd"], 4),
                 number(row["seconds"], 0), number(float(row["total_tokens"]) / 1000, 1),
                 {"admitted": "Y", "rejected": "N"}.get(row["visual_decision"], "?")]
        rendered = [r"\raggedright " + latex(value) if value is not None else
                    r"\raisebox{-.75\height}{\includegraphics[width=30pt]{" + row["thumbnail"] + "}}" for value in cells]
        report.add(" & ".join(rendered) + r"\tabularnewline")
    report.add(r"\bottomrule\end{tabular*}\endgroup\par\medskip")
    report.add(r"{\footnotesize " + latex("Syn/Sem/Lay counts syntactic, semantic and layout failures. R averages retained text, link destinations and image references. Costs and tokens include the recorded execution stages. The output is the selected version; visual acceptance is independent. Component retention, assessment coverage and all measured iteration paths are in the exported CSV files.") + r"}\par")


def write_source(evidence, directory):
    report = Report()
    runs = evidence["runs"]
    total_cost = sum(Decimal(row["cost_usd"]) for row in runs)
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
\noindent\textcolor{HarnessBlue}{\textbf{SUPPLEMENTARY MATERIAL / EXPERIMENT 2}}\par\bigskip
\noindent{\LARGE\bfseries Harness Engineering for Web Accessibility\par}
\medskip
\noindent{\Large Orchestrating Automated Remediation with Agents and LLMs\par}
\vspace{22pt}
\noindent Guillermo Vera-Amaro and José Rafael Rojano-Cáceres\par
\medskip
\noindent Facultad de Estadística e Informática\par
\noindent Universidad Veracruzana, Xalapa, Mexico\par
\vspace{24pt}
\noindent{\Large\bfseries\textcolor{HarnessBlue}{Experiment 2. Fixed intervention trade-offs}\par}
\medskip
This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection. This companion connects the fixed intervention comparison to its saved source pages, selected outputs, measured versions, prompts, skills, task contracts and execution resources. Each domain has fifteen conditions, combining P0--P4 with three repair configurations.\par\bigskip
\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lll@{}}\toprule
\textbf{30} frozen sources & \textbf{450} selected runs & \textbf{1,074} evaluated versions\\\bottomrule
\end{tabular*}\par\bigskip
P0 provides a direct zero-shot HTML comparator. P1 and P2 use constrained local patches; P3 and P4 generate a new page from HTML and Markdown, respectively. The following pages expose their accessibility, preservation, visual and resource outcomes on matched source states.
\end{titlepage}
""")
    report.heading("Matched outcomes and preservation")
    table = []
    for policy in POLICIES:
        rows = [row for row in runs if row["policy"] == policy]
        original = sum(float(row["original_axe"]) for row in rows)
        correction = 100 * (original - sum(float(row["axe"]) for row in rows)) / original
        table.append([policy, len(rows), number(mean(float(row["axe"]) for row in rows), 2) + "/" + number(mean(float(row["lighthouse"]) for row in rows), 1),
                      number(correction, 1), number(median(float(row["content_retention"]) for row in rows), 2),
                      str(sum(row["visual_decision"] == "admitted" for row in rows)) + "/90",
                      sum(int(row["evaluated_versions"]) for row in rows), number(sum(Decimal(row["cost_usd"]) for row in rows))])
    report.table(["Policy", "Runs", "Mean Axe/LH", "Axe removed %", "Median R %", "Visual accepted", "Versions", "Total USD"], table, [8, 7, 15, 15, 14, 15, 11, 13])
    report.paragraph("Axe removal pools source and output instance counts across each policy's ninety conditions. Content retention R is the per-output mean of retained text, original link destinations and source image references; the table reports its median. Visual judgments are independent of audit selection. Unassessed checks do not count as passes.")
    report.heading("Repair configurations and resource accounting", subsection=True)
    report.table(["Configuration", "Runs", "Input tokens K", "Output tokens K", "Time h", "Total USD"], [
        [label, len(rows), number(sum(int(row["input_tokens"]) for row in rows) / 1000, 1),
         number(sum(int(row["output_tokens"]) for row in rows) / 1000, 1),
         number(sum(float(row["seconds"]) for row in rows) / 3600, 2), number(sum(Decimal(row["cost_usd"]) for row in rows))]
        for profile, label in [("luna-light", "GPT-Luna 6 light"), ("luna-high", "GPT-Luna 6 high"), ("haiku-low", "Haiku 5.5 light")]
        for rows in [[row for row in runs if row["profile"] == profile]]], [30, 8, 19, 19, 11, 13])
    report.paragraph("Complete selected-execution cost is US$" + number(total_cost) + ". Charges include generation, planning where applicable, model-based assessment and unsuccessful proposals within the analyzed execution scope. Call identities link these totals to their receipts. Durations are recorded workflow clocks; they are not sums of provider response times.")
    report.page()
    report.heading("Source-paired statistical comparisons")
    statistics = evidence["paired-statistics"]
    report.paragraph("Each comparison pairs the same source under two policies and averages its three worker-specific differences. This makes the domain the analysis unit and prevents counting three configurations as independent pages. The saved two-sided exact sign-flip test compares the mean paired difference, with Holm control across the ten policy contrasts for each metric. The table labels these reported probabilities p.")
    report.table(["First/second", "Correction pp", "Retention pp", "Cost USD", "Time s", "p correction", "p retention"], [
        [contrast["first"] + "/" + contrast["second"],
         number(contrast["effects"]["reduction"]["mean_difference"], 1),
         number(contrast["effects"]["content"]["mean_difference"], 1),
         number(contrast["effects"]["cost"]["mean_difference"], 4),
         number(contrast["effects"]["seconds"]["mean_difference"], 1),
         p_value(contrast["effects"]["reduction"]["holm_p"]), p_value(contrast["effects"]["content"]["holm_p"])]
        for contrast in statistics["policy_contrasts"]], [18, 14, 14, 14, 14, 13, 13])
    report.paragraph("Differences are second minus first. Correction and retention use percentage points (pp); positive correction or retention favors the second policy, while negative time or cost favors it. Per-domain correction can be negative when a generated output adds findings. These domain-weighted effects differ from the pooled correction percentages in the preceding overview.")
    report.paragraph("paired-statistics.json preserves the domain differences, exact probabilities, Holm results and 95% percentile bootstrap intervals from 10,000 domain resamples, including the saved seed. It also retains the five GPT-Luna 6 effort contrasts. The report reads these saved analyses rather than rerunning statistical tests or introducing new observations.")
    report.page()
    report.heading("Recorded zero-shot and local-repair prompts")
    examples = evidence["prompt-examples"]
    report.heading("P0 direct HTML correction", subsection=True)
    report.quote(example_text(examples["P0"]))
    report.paragraph("Recorded request " + examples["P0"]["call_id"] + " (run " + str(examples["P0"]["run_id"]) + "). The source HTML follows this instruction. Generation receives no supplied audit findings or iterative repair feedback; post-generation instruments measure the returned page.")
    report.heading("P1 and P2 constrained operations", subsection=True)
    patch = example_text(examples["P1"])
    report.quote(patch.split("Patch prompt version:")[0].strip())
    for policy in ("P1", "P2"):
        text = example_text(examples[policy])
        intervention = next(line for line in text.splitlines() if line.startswith("Intervention:"))
        report.quote(policy + ": " + intervention.removeprefix("Intervention: "))
    report.paragraph("The complete request combines these instructions with the versioned task skill, permitted operations, measured findings, current document evidence and applicable ACT examples. The saved prompts.csv and instruction hashes link each iteration to its actual request; P1 and P2 do not share identical edit permissions.")
    report.page()
    report.heading("Regeneration, RAG and refinement evidence")
    report.heading("P3 HTML and P4 Markdown regeneration", subsection=True)
    report.quote(example_text(examples["P3"]))
    report.paragraph("P3 supplies source HTML and P4 supplies its verified Markdown representation under the shared generation instruction. Page purpose, category, source URL, assets and saved capture provide context. Subsequent correction uses measured feedback and the recorded refinement contract. Examples and request hashes for both representations remain in prompt-examples.json.")
    if "rag" in examples:
        report.heading("ACT RAG in the repair request", subsection=True)
        rag = examples["rag"]["text"].replace("\\n", "\n")
        report.quote(re.split(r"Code example:", rag, maxsplit=1, flags=re.I)[0].strip())
        report.paragraph("This injected excerpt occurs in request " + examples["rag"]["call_id"] + ". rag.json records the ACT corpus, query hashes, requested rules and injected case identities per iteration. The retrieved requirement is supplied with the measured findings in the same generation request; empty retrieval is preserved explicitly.")
    report.paragraph("prompts.csv includes repair and continuation calls with instruction hashes. message-parts.csv binds supplied text/image parts to their original sizes and hashes. Full page payloads are not included in this reader package, which retains the recorded instruction excerpts and their complete-request identities.")
    report.page()
    report.heading("Skills, tools and task contracts")
    report.table(["Task / tool", "Input and output contract"], [
        ["Acquisition and transformation", "Bind the frozen input, capture and inventory; supply HTML for P0/P3, verified Markdown for P4, and scoped document evidence for P1/P2."],
        ["ACT retrieval", "Match measured rules to attributed passed/failed examples; record corpus, query and injected identities."],
        ["Component planning / diagnosis", "Support coordinated P2 causes and dependencies, or interpret unresolved findings without expanding the assigned policy."],
        ["Constrained patch application", "Validate selectors, operation permissions, protected content and native controls before applying proposals."],
        ["Candidate evaluation", "Record Axe/Lighthouse, retention inventories, taxonomic failures/coverage and independent visual review."],
        ["Continuation / selection", "Use the measured trajectory and closed advice under fixed strategy/model and deterministic attempt, time and monetary limits."],
    ], [32, 68])
    report.table(["Recorded skill", "Instruction"], [[skill["id"] + " @ " + skill["version"], skill["instruction"]] for skill in evidence["skills"]], [36, 64])
    report.paragraph("The coordinator calls execution tools and validates responses. Skills supply task instructions; they do not execute changes or grant authority. Each run's saved controller, model/provider configuration, task limits and refinement settings remain in protocol.json.")
    for source in evidence["sources"]:
        write_domain(report, evidence, source)
    report.page()
    report.heading("Execution resources and evidence map")
    roles = defaultdict(lambda: {"count": 0, "input": 0, "output": 0, "cost": Decimal("0")})
    for call in evidence["requests"]:
        if call["in_analysis"] != "True":
            continue
        group = roles[call["role"]]
        group["count"] += 1
        group["input"] += int(call["input_tokens"] or 0)
        group["output"] += int(call["output_tokens"] or 0)
        group["cost"] += Decimal(call["cost_usd"])
    report.table(["Recorded task", "Calls", "Input tokens K", "Output tokens K", "USD"], [
        [role, values["count"], number(values["input"] / 1000, 1), number(values["output"] / 1000, 1), number(values["cost"], 6)]
        for role, values in sorted(roles.items())], [30, 10, 23, 23, 14])
    included = sum(values["cost"] for values in roles.values())
    assert abs(included - total_cost) < Decimal("0.00001")
    report.paragraph("The published total is US$" + number(total_cost, 6) + ". accounting.csv reconciles each analyzed execution with its included receipt identities. Published aggregation precision and individual receipt precision remain explicit.")
    report.heading("Traceability and regeneration", subsection=True)
    report.paragraph("sources.csv binds thirty original captures to frozen input hashes. runs.csv links every selected output to its run, policy, model, audit, capture, retention, taxonomy and resource measurements. iterations.csv retains all 1,074 analyzed versions and selection markers. bindings.json connects each condition to its selected artifacts and call identities. Internal artifact references use stable SHA-256 identifiers.")
    report.paragraph("taxonomy.csv preserves original and selected failures, opportunities, coverage and unassessed checks. taxonomy-types.json adds the saved rule-level outcomes. decisions.json, rag.json and the prompt exports connect the measured trajectories to advice and injected evidence. Rebuilding this report uses these local exports without acquiring pages, running models, changing captures or modifying human reviews.")
    report.add(r"\end{document}")
    (directory / "main.tex").write_text("\n".join(report.blocks) + "\n")
    return {"sources": 30, "runs": 450, "evaluated_versions": 1074, "published_cost_usd": str(total_cost),
            "recorded_calls": len(evidence["requests"]), "prompt_calls": len(evidence["prompts"]),
            "exported_files_checked": evidence["exported_files_checked"]}


def compile_pdf(directory, output):
    with tempfile.TemporaryDirectory(prefix="supp-e2-latex-") as temporary:
        build = Path(temporary)
        process = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-outdir=" + str(build), "main.tex"],
                                 cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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
    return {"pages": len(reader.pages), "bytes": output.stat().st_size, "warnings": warnings,
            "pdf_sha256": digest(output.read_bytes()), "tex_sha256": digest((directory / "main.tex").read_bytes()),
            "class_sha256": digest((directory / "acmart.cls").read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-source", action="store_true", help="Explicitly rebuild main.tex from exported evidence.")
    parser.add_argument("--output", type=Path, default=EXPERIMENT_DIR / "supplementary.pdf")
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
