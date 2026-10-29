"""Build Experiment 3 supplementary material from the files in this folder.

Default compilation preserves edits to main.tex. --refresh-source explicitly
rebuilds the editable LaTeX from checked CSV/JSON exports and small thumbnails.
No database, website, model API, or running Harness service is required.
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
from pathlib import Path

EXPERIMENT_DIR = Path(__file__).resolve().parent
FAMILIES = ("luna", "haiku", "sol", "sonnet", "astra", "opus")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_csv(directory, name):
    with (directory / "data" / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def load_evidence(directory):
    manifest = json.loads((directory / "data/checksums.json").read_text())
    for relative, expected in manifest["files"].items():
        if digest((directory / relative).read_bytes()) != expected:
            raise ValueError("Exported evidence changed: " + relative)
    evidence = {name: read_csv(directory, name + ".csv")
                for name in ("sources", "runs", "iterations", "requests", "generation-prompts", "taxonomy")}
    for call in evidence["requests"]:
        call["run"] = "sql-run-" + str(call["run"]).removeprefix("sql-run-")
    for name in ("protocol", "skills", "prompt-examples"):
        evidence[name] = json.loads((directory / "data" / (name + ".json")).read_text())
    evidence["exported_files_checked"] = len(manifest["files"])
    assert len(evidence["runs"]) == 12 and len(evidence["iterations"]) == 20
    return evidence


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


def write_source(evidence, output_dir):
    report = Report()
    runs = evidence["runs"]
    protocol = evidence["protocol"]
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
\noindent\textcolor{HarnessBlue}{\textbf{SUPPLEMENTARY MATERIAL / EXPERIMENT 3}}\par\bigskip
\noindent{\LARGE\bfseries Harness Engineering for Web Accessibility\par}
\medskip
\noindent{\Large Orchestrating Automated Remediation with Agents and LLMs\par}
\vspace{22pt}
\noindent Guillermo Vera-Amaro and José Rafael Rojano-Cáceres\par
\medskip
\noindent Facultad de Estadística e Informática\par
\noindent Universidad Veracruzana, Xalapa, Mexico\par
\vspace{24pt}
\noindent{\Large\bfseries\textcolor{HarnessBlue}{Experiment 3. Model family and reasoning effort}\par}
\medskip
This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection. This companion records the twelve P4 executions used to examine effort-related content preservation across model families under shared harness controls. It joins their saved source and selected outputs with measured results, prompt and RAG evidence, task contracts, and complete execution resources.\par
\bigskip
\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lll@{}}\toprule
\textbf{1} frozen source & \textbf{12} model configurations & \textbf{20} evaluated versions\\\bottomrule
\end{tabular*}\par\bigskip
The same TIME page, P4 intervention, and initial messages are used for six models at light and high effort. Every retained output reaches Axe 0 and Lighthouse 100. Higher effort increases content retention in all six within-model comparisons, by 8.22--40.97 percentage points. The selected configurations span 25.84--85.30\% retention. These are descriptive results on one source, with visual judgments and content loss reported separately from audit success.
\end{titlepage}
""")
    report.heading("Shared source and selected endpoints")
    source = evidence["sources"][0]
    report.add(r"\noindent\begin{minipage}[t]{.36\linewidth}\vspace{0pt}\includegraphics[width=\linewidth]{" + source["thumbnail"] + r"}\end{minipage}\hfill\begin{minipage}[t]{.60\linewidth}\vspace{0pt}\small\textbf{Frozen starting page}\par\smallskip\url{https://time.com/}\par\smallskip Source \#358\par Axe 10 / Lighthouse 91\par Syntactic / semantic / layout failures: 1 / 64 / 9\par\smallskip Input SHA-256 prefix\par\nolinkurl{" + protocol["source_sha256"][:24] + r"}\end{minipage}\par\medskip")
    report.table(["Configuration", "Axe/LH", "Content %", "T/L/I %", "Syn/Sem/Lay"], [
        [row["model"] + " " + row["effort"], row["axe"] + "/" + row["lighthouse"],
         number(row["content_retention"]), "/".join(number(row[key]) for key in ("text_percent", "links_percent", "images_percent")),
         "/".join(row[key + "_failures"] for key in ("syntactic", "semantic", "layout"))]
        for row in runs], [27, 12, 13, 34, 14])
    report.paragraph("Content retention is the arithmetic mean of retained text, link destinations, and source-image references. Syn/Sem/Lay denotes syntactic, semantic, and layout failures. Static image size and encoding variants follow the saved source-asset identity analysis. Missing or unassessed opportunities are not counted as passes.")
    report.paragraph("Selection and visual acceptance are distinct. Audit targets determine the retained experimental endpoint; the recorded visual judgment remains separate. All selected screenshots below are the saved captures linked to those endpoints.")
    report.page()
    report.heading("Recorded prompts and RAG")
    examples = evidence["prompt-examples"]
    initial = examples["initial"]
    initial_parts = initial["parts"]
    base_instruction = next(part["text"] for part in initial_parts if part["role"] == "system")
    report.heading("Initial generation contract", subsection=True)
    report.quote(base_instruction)
    report.paragraph("Recorded request " + initial["call_id"] + " (run " + str(initial["run_id"]) + ").")
    report.heading("RAG evidence in the same request", subsection=True)
    rag_text = next(part["text"] for part in initial_parts if part["text"].startswith("Accessibility evidence"))
    first_case = re.split(r"Accessibility evidence 2", rag_text)[0].strip()
    report.quote(first_case)
    report.paragraph("The same initial request also contains complete Markdown, the page-design brief, acquired-page context, the source screenshot, and four retrieved ACT cases. The quoted example is part of that request, alongside the generation contract. The twelve initial message arrays share SHA-256 prefix " + protocol["initial_messages_sha256"][:24] + ".")
    report.page()
    report.heading("Refinement, skills, and execution", subsection=True)
    refinement = examples["refinement"]
    refinement_text = refinement["parts"][0]["text"]
    intervention = next(line for line in refinement_text.splitlines() if line.startswith("Intervention:"))
    report.quote(refinement_text.split("Patch prompt version:")[0].strip() + "\n" + intervention)
    report.paragraph("Recorded refinement request " + refinement["call_id"] + " (run " + str(refinement["run_id"]) + "). The initial stage returns a complete HTML document. Later proposals use local operations on that generated document, with current measurements and feedback supplied to the same repair model.")
    report.table(["Task / execution tool", "Recorded contract"], [
        ["P4 generation", "Create complete standalone HTML from Markdown and contextual references; reuse trustworthy facts, destinations, and assets."],
        ["apply_constrained_patch", "Validate refinement selectors and permitted local operations; preserve the current content, controls, and working layout."],
        ["retrieve_accessibility_evidence", "Map observed barriers to ACT examples and record the corpus, query, and injected example identities."],
        ["evaluate_candidate / measure_content_retention", "Record Axe, Lighthouse, source inventories, taxonomy coverage, syntax, and an independent visual judgment."],
        ["select_best_candidate / continue-stop", "Retain the measured result and stop at the first retained Axe 0/Lighthouse 100 endpoint within recorded resource limits."],
    ], [39, 61])
    report.paragraph("The deterministic coordinator calls execution tools and enforces their contracts. Models supply documents, patch proposals, contextual judgments, and continuation advice. GPT-Luna 6 Decisions assesses textual context; GPT-Luna 6 light assesses image alternatives and visual usability.")
    report.table(["Versioned skill", "Instructions"], [
        [skill["id"] + " @ " + skill["version"], skill["instruction"]]
        for skill in evidence["skills"]], [38, 62])
    for family in FAMILIES:
        report.page()
        pair = [row for row in runs if row["profile"].split("-")[0] == family]
        light, high = sorted(pair, key=lambda row: row["effort"] == "high")
        gain = float(high["content_retention"]) - float(light["content_retention"])
        report.heading(light["model"] + " -- light and high effort")
        report.paragraph("Higher effort adds " + number(gain) + " content-retention points at the same Axe 0/Lighthouse 100 endpoint.")
        for index, row in enumerate((light, high)):
            report.add(r"\begin{minipage}[t]{.47\linewidth}\vspace{0pt}\centering\includegraphics[width=.82\linewidth]{" + row["thumbnail"] + r"}\par\smallskip\footnotesize\textbf{" + latex(row["model"] + " " + row["effort"]) + r"}\par Run " + row["run_id"] + r"\end{minipage}" + (r"\hfill" if index == 0 else r"\par\medskip"))
        measures = [
            ("Axe / Lighthouse", lambda row: row["axe"] + " / " + row["lighthouse"]),
            ("Syntactic / semantic / layout", lambda row: " / ".join(row[key + "_failures"] for key in ("syntactic", "semantic", "layout"))),
            ("Content retention (%)", lambda row: number(row["content_retention"])),
            ("Text / links / images (%)", lambda row: " / ".join(number(row[key]) for key in ("text_percent", "links_percent", "images_percent"))),
            ("Taxonomy coverage Syn/Sem/Lay (%)", lambda row: " / ".join(number(float(row[key + "_coverage"]) * 100, 1) for key in ("syntactic", "semantic", "layout"))),
            ("Automatic visual decision", lambda row: visual_label(row["visual_decision"])),
            ("Evaluated versions", lambda row: row["iterations"]),
            ("Input / output tokens", lambda row: number(row["input_tokens"], 0) + " / " + number(row["output_tokens"], 0)),
            ("Recorded time (s)", lambda row: number(row["seconds"], 1)),
            ("Complete execution cost (USD)", lambda row: number(row["cost_usd"], 4)),
        ]
        report.table(["Measure", "Light", "High"], [[label, function(light), function(high)] for label, function in measures], [40, 30, 30])
        paths = []
        trace = []
        for row in (light, high):
            versions = [version for version in evidence["iterations"] if version["run_id"] == row["run_id"]]
            paths.append([row["effort"], " / ".join(v["axe"] + ("*" if v["chosen"] == "True" else "") for v in versions),
                          " / ".join(v["lighthouse"] + ("*" if v["chosen"] == "True" else "") for v in versions)])
            selected_step = next(v["iteration"] for v in versions if v["chosen"] == "True")
            calls = [call for call in evidence["requests"] if call["run"] == "sql-run-" + row["run_id"]]
            generation = [prompt for prompt in evidence["generation-prompts"] if prompt["run_id"] == row["run_id"]]
            selected_prompt = next(prompt for prompt in reversed(generation) if prompt["iteration"] == selected_step)
            trace.append([row["effort"], str(len(generation)) + " / " + str(len(calls) - len(generation)),
                          selected_step, selected_prompt["call_id"][:12], selected_prompt["request_sha256"][:12]])
        report.table(["Effort", "Axe by evaluated version", "Lighthouse by evaluated version"], paths, [15, 40, 45])
        report.paragraph("An asterisk marks the selected version. Paths follow evaluation order.")
        report.table(["Effort", "Generation / other calls", "Selected iteration", "Selected call", "Request SHA"], trace, [12, 25, 20, 21, 22])
    report.page()
    report.heading("Resource and evidence ledger")
    groups = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cost": Decimal("0")})
    for call in evidence["requests"]:
        group = groups[call["role"]]
        group["calls"] += 1
        group["input"] += int(call["input_tokens"])
        group["output"] += int(call["output_tokens"])
        group["cost"] += Decimal(call["cost_usd"])
    report.table(["Recorded task", "Calls", "Input tokens", "Output tokens", "USD"], [
        [role, group["calls"], number(group["input"], 0), number(group["output"], 0), number(group["cost"], 6)]
        for role, group in sorted(groups.items())] + [["Total", len(evidence["requests"]),
            number(sum(group["input"] for group in groups.values()), 0), number(sum(group["output"] for group in groups.values()), 0), number(total_cost, 6)]], [32, 10, 22, 22, 14])
    report.paragraph("Complete execution cost totals US$" + number(total_cost, 6) + " (US$" + number(total_cost) + " rounded). It includes generation, refinements, and the recorded assessment calls belonging to these twelve executions. Per-run wall-clock durations remain observed values.")
    report.heading("Recorded visual rejection reasons", subsection=True)
    rejected = [row for row in runs if row["visual_decision"] == "rejected"]
    report.table(["Selected configuration", "Recorded rationale"], [
        [row["model"] + " " + row["effort"], row["visual_rationale"]]
        for row in rejected], [24, 76])
    report.paragraph("Full visual rationales for all twelve configurations remain in runs.csv. These saved judgments are independent of audit-based selection.")
    report.heading("Traceability", subsection=True)
    report.paragraph("runs.csv binds each endpoint to its original source, runtime, model configuration, audit, selected document, taxonomy assessment, and snapshot. iterations.csv identifies every evaluated version. generation-prompts.csv links all twenty generation/refinement requests to exported instructions and message-part hashes; rag.json retains the injected ACT identities. The package checksums cover the CSV/JSON evidence and all thirteen small thumbnails.")
    report.add(r"\end{document}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "main.tex").write_text("\n".join(report.blocks) + "\n")
    return {"runs": 12, "evaluated_versions": 20, "generation_requests": len(evidence["generation-prompts"]),
            "recorded_calls": len(evidence["requests"]), "cost_usd": str(total_cost),
            "exported_files_checked": evidence["exported_files_checked"]}


def compile_pdf(directory, output):
    with tempfile.TemporaryDirectory(prefix="supp-e3-latex-") as temporary:
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
