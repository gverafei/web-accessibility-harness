"""Generate the supplementary report exclusively from this experiment's exported files.

Default compilation preserves edits to main.tex. --refresh-source explicitly
rebuilds that editable source from the checked CSV/JSON evidence and thumbnails.
No database, software service, network access, model call, or new capture is used.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, shutil, subprocess, tempfile
from pathlib import Path
from types import SimpleNamespace

HOME = Path(__file__).resolve().parent
SOURCE = HOME / 'data/runs.csv'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def read_csv(name):
    with (HOME/'data'/name).open(newline='',encoding='utf-8') as stream:
        return list(csv.DictReader(stream))

def load_evidence():
    manifest=json.loads((HOME/'data/checksums.json').read_text())
    for relative,expected in manifest['files'].items():
        assert sha((HOME/relative).read_bytes())==expected, 'Exported input changed: '+relative
    sources=read_csv('sources.csv'); runs=read_csv('runs.csv'); iterations=read_csv('iterations.csv'); requests=read_csv('requests.csv')
    examples={p['call_id']:p for p in json.loads((HOME/'data/prompt-examples.json').read_text())}
    skills={(s['id'],s['version'],s['digest']):s['instruction'] for s in json.loads((HOME/'data/skills.json').read_text())}
    protocol=json.loads((HOME/'data/protocol.json').read_text())
    domains={}
    for s in sources:
        domains[s['domain']]={'baseline':{'axe':int(s['axe']),'lighthouse':int(s['lighthouse'])},
            'rank':int(s['rank']),'source':int(s['source_id']),
            'shared':{'cost_usd':float(s['shared_cost_usd'])},
            'page':{'source':{'url':s['url']},'capture_id':s['capture_id']},
            'preview':{'path':str(HOME/s['thumbnail']),'artifact_id':s['screenshot_artifact_id']}}
    generation_steps={r['call_id']:int(r['iteration']) for r in read_csv('generation-prompts.csv')}
    calls=[];prompts=[]
    for c in requests:
        c['run']='sql-run-'+str(c['run']).removeprefix('sql-run-')
        c['input_tokens']=int(c['input_tokens'] or 0);c['output_tokens']=int(c['output_tokens'] or 0)
        c['cost']=float(c['cost_usd'] or 0);calls.append(c)
        c['iteration']=generation_steps.get(c['id'])
        if c['role']=='Repair generation':
            p=examples.get(c['id'],{})
            prompts.append({'call':c,'text':p.get('instruction_text',''),
                'request':{'messages':[{'role':'system','content':text} for text in p.get('system_instructions',[])]}})
    rows=[]
    for record in runs:
        r=dict(record)
        for name in ('rank','source','repeat','run_id','axe','lighthouse','evaluated_candidates','input_tokens','output_tokens'):
            r[name]=int(r[name])
        for name in ('cost_usd','seconds','cohort_allocated_cost_usd','cohort_allocated_tokens'):r[name]=float(r[name])
        r['failed']={k:int(r[field]) for k,field in [('Syntactic','syntactic_failures'),('Semantic','semantic_failures'),('Layout','layout_failures')]}
        r['retention']={k:float(r[k]) for k in ('text_percent','links_percent','images_percent')}
        r['coverage']={k:float(r[field]) for k,field in [('Syntactic','syntactic_coverage'),('Semantic','semantic_coverage'),('Layout','layout_coverage')]}
        r['manifest']={'runtime_snapshot':{'code_digest':r['runtime_digest']}}
        r['preview']={'path':str(HOME/r['thumbnail']),'artifact_id':r['screenshot_artifact_id']}
        r['calls_detail']=[c for c in calls if c['run']=='sql-run-'+str(r['run_id'])]
        r['attempts_detail']=[]
        for a in iterations:
            if int(a['run_id'])!=r['run_id']:continue
            r['attempts_detail'].append({'id':a['attempt_id'],'audit_id':a['audit_id'],'iteration':int(a['iteration']),
                'audit':{'axe':int(a['axe']),'lighthouse':int(a['lighthouse'])},
                'chosen':a['chosen']=='True'})
        rows.append(r)
    assert len(rows)==30 and sum(len(r['attempts_detail']) for r in rows)==116
    return SimpleNamespace(rows=rows,domains=domains,summary={'domains':[s['domain'] for s in sources]},
        prompts=prompts,skills=skills,integrity={'exported_files_checked':len(manifest['files'])},protocol=protocol)

def latex(value):
    substitutions={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_',
        '{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
    return ''.join(substitutions.get(c,c) for c in str(value)).replace('\n',r'\newline ')


def write_source(e, source_dir):
    source_dir.mkdir(parents=True,exist_ok=True)
    figures=source_dir/'thumbnails';figures.mkdir(exist_ok=True)
    if not (source_dir/'acmart.cls').exists():
        raise FileNotFoundError('The exported ACM class is required alongside main.tex.')
    source=[]
    def emit(s):source.append(s)
    def paragraph(s):emit(latex(s)+'\n')
    def heading(s):emit(r'\section{'+latex(s)+'}\n')
    def sub(s):emit(r'\subsection{'+latex(s)+'}\n')
    def table(headers,rows,weights):
        total=sum(weights)
        cols=[]
        for i,w in enumerate(weights):
            cols.append('p{'+(f'{w/total:.4f}\\linewidth' if i==0 else f'\\dimexpr{w/total:.4f}\\linewidth-2\\tabcolsep\\relax')+'}')
        emit(r'\begingroup\footnotesize\setlength{\tabcolsep}{3pt}\renewcommand{\arraystretch}{1.14}')
        emit(r'\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}'+''.join(cols)+r'@{}}\toprule')
        emit(' & '.join(r'\raggedright\textbf{'+latex(h)+'}' for h in headers)+r'\tabularnewline\midrule')
        for row in rows:emit(' & '.join(r'\raggedright '+latex(v) for v in row)+r'\tabularnewline')
        emit(r'\bottomrule\end{tabular*}\endgroup\par\medskip'+'\n')
    def quote(s):
        emit(r'\begin{quote}\footnotesize\ttfamily\raggedright\sloppy '+latex(s)+r'\end{quote}'+'\n')
    emit(r'''%% Reader-facing supplementary material. Edit this file directly and use make.
%% Python refreshes the data-derived source only with --refresh-source.
\documentclass[acmsmall,screen,nonacm]{acmart}
\acmJournal{TWEB}
\setcopyright{none}
\acmDOI{}
\settopmatter{printacmref=false,printccs=false,printfolios=true}
\definecolor{HarnessBlue}{HTML}{18529D}
\title[Supplementary Material -- Experiment 1]{Harness Engineering for Web Accessibility}
\subtitle{Orchestrating Automated Remediation with Agents and LLMs}
\author{Guillermo Vera-Amaro}
\author{José Rafael Rojano-Cáceres}
\affiliation{\institution{Universidad Veracruzana}\city{Xalapa}\country{Mexico}}
\renewcommand{\shortauthors}{Vera-Amaro and Rojano-Cáceres}
\renewcommand{\thesection}{S\arabic{section}}
\makeatletter
\g@addto@macro\@secfont{\Large}
\makeatother
\begin{document}
\raggedbottom
\pagestyle{plain}
\begin{titlepage}
\vspace*{12pt}
\noindent\textcolor{HarnessBlue}{\textbf{SUPPLEMENTARY MATERIAL / EXPERIMENT 1}}\par\bigskip
\noindent{\LARGE\bfseries Harness Engineering for Web Accessibility\par}
\medskip
\noindent{\Large Orchestrating Automated Remediation with Agents and LLMs\par}
\vspace{22pt}
\noindent Guillermo Vera-Amaro and José Rafael Rojano-Cáceres\par
\medskip
\noindent Facultad de Estadística e Informática\par
\noindent Universidad Veracruzana, Xalapa, Mexico\par
\vspace{24pt}
\noindent{\Large\bfseries\textcolor{HarnessBlue}{Experiment 1. Harness determinism}\par}
\medskip
This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection. This companion documents the thirty selected executions used to examine repeatability under harness controls. It brings together the frozen starting pages, selected outputs, version-level audit results, preservation measurements, resource use, and recorded prompt and execution evidence.\par
\bigskip
\noindent\begin{tabular*}{\linewidth}{@{\extracolsep{\fill}}lll@{}}\toprule
\textbf{5} frozen sources & \textbf{30} independent runs & \textbf{116} evaluated versions\\\bottomrule
\end{tabular*}\par
\bigskip
Five sources were each repaired with P1 and P2, with three independent repetitions per strategy using GPT-Luna 6 high. Final Axe endpoints coincide within all ten source--strategy groups. Lighthouse varies by at most one point and semantic failures by at most two. All thirty selected outputs retain the measured source text, links, and images.
\end{titlepage}
''')
    heading('Execution contracts')
    paragraph('GPT-Luna 6 high performs repair generation, component planning, and diagnosis. GPT-Luna 6 Decisions provides contextual assessment and continuation advice, while GPT-Luna 6 light supplies visual and image judgments. The deterministic coordinator applies operations, invokes measurement tools, enforces permissions and resource limits, and retains the selected candidate.')
    table(['Task','Input and output contract'],[
        ['Source verification','Use saved source and replay evidence to record a grounded usability judgment.'],
        ['Component planning / diagnosis','Plan related P2 changes or interpret stalled progress within the assigned repair scope.'],
        ['Repair generation','Return a JSON operations array and concise rationale. P2 also groups operations by supported root causes and dependencies.'],
        ['Measurement','Record Axe/Lighthouse audits, taxonomy findings, source retention, technical checks, and visual review separately.'],
        ['Continue / stop','Recommend continuation or stopping from measurements and remaining resources; the deterministic coordinator validates the recommendation.']],[94,284])
    sub('Permitted operations')
    paragraph('P1 permits attribute and name corrections, adjacent labels or descriptions, and targeted contrast/focus CSS. P2 additionally permits supported small subtree replacements, list wrapping, and local keyboard/focus JavaScript. Selectors, protected content, original control contracts, and P2 component dependencies are checked before application.')
    table(['Tool interface','Task'],[
        ['inspect_dom / read_axe_evidence / read_lighthouse_evidence','Supply document context and measured barriers.'],
        ['retrieve_accessibility_evidence','Supply admissible ACT cases or record abstention.'],
        ['apply_constrained_patch','Validate permissions and apply scoped operations.'],
        ['evaluate_candidate / measure_content_retention','Record audits, captures, and retained inventories.'],
        ['plan_components / select_best_candidate','Support P2 planning and deterministic candidate selection.']],[184,194])
    sub('Execution limits')
    paragraph('The saved configuration permits ten proposal opportunities, with US$5 per paid call and per run. The 1,800-second reference is progress-sensitive under the recorded time policy. Targets are at most five Axe instances and at least 90 Lighthouse points.')
    emit(r'\clearpage')
    heading('Recorded prompts and skills')
    paragraph('Repair requests combine the intervention contract, localized document context, audit findings, current feedback, and versioned skills. Admissible ACT examples are included when available. P2 may add the recorded component plan. Later requests use the current repair state while keeping the strategy and model fixed.')
    p1=next(p for p in e.prompts if p['call']['run']=='sql-run-1219')
    sub('Shared generation instruction')
    quote(p1['text'].split('Patch prompt version:')[0].strip())
    for policy in ('P1','P2'):
        row=next(r for r in e.rows if r['policy']==policy)
        prompt=next(p for p in e.prompts if p['call']['run']=='sql-run-'+str(row['run_id']))
        contract=next(line for line in prompt['text'].splitlines() if line.startswith('Intervention:'))
        sub(policy+' intervention instruction')
        quote(contract)
    sub('Refinement instruction')
    instructions=[m['content'] for m in p1['request'].get('messages',[]) if m.get('role')=='system' and isinstance(m.get('content'),str)]
    if instructions:quote(instructions[-1])
    sub('Versioned skills')
    table(['Skill','Instruction'],[[sid+' @ '+version,instruction] for (sid,version,h),instruction in sorted(e.skills.items())],[138,240])
    for domain in e.summary['domains']:
        group=[r for r in e.rows if r['domain']==domain];d=e.domains[domain]
        emit(r'\clearpage');heading(domain+' -- source and selected outputs')
        paragraph(f"Frozen source #{d['source']}; Tranco rank {d['rank']}; original Axe {d['baseline']['axe']} / Lighthouse {d['baseline']['lighthouse']}. Six independent runs use GPT-Luna 6 high, with three repetitions each for P1 and P2.")
        original=Path(d['preview']['path']).name
        emit(r'\noindent\begin{minipage}[t]{.49\linewidth}\vspace{0pt}\includegraphics[width=\linewidth]{thumbnails/'+original+r'}\end{minipage}\hfill\begin{minipage}[t]{.47\linewidth}\vspace{0pt}\small\textbf{Frozen starting page}\par\smallskip\url{'+d['page']['source']['url']+r'}\par\smallskip Source '+str(d['source'])+r'\par\smallskip Input SHA-256 prefix\par\nolinkurl{'+group[0]['input_sha256'][:24]+r'}\end{minipage}\par\medskip')
        for half in (group[:3],group[3:]):
            emit(r'\noindent')
            for j,row in enumerate(half):
                a=next(a for a in row['attempts_detail'] if a['chosen']);step=a['iteration']
                f=Path(row['preview']['path']).name
                emit(r'\begin{minipage}[t]{.32\linewidth}\vspace{0pt}\includegraphics[width=\linewidth]{thumbnails/'+f+r'}\par\smallskip\footnotesize\textbf{'+latex(f"{row['policy']} / R{row['repeat']} / run {row['run_id']}")+r'}\par '+latex(f"Selected iteration {step}")+r'\par '+latex(f"Axe {row['axe']} / LH {row['lighthouse']}")+r'\end{minipage}'+(r'\hfill' if j<2 else ''))
            emit(r'\par\medskip')
        table(['Run / R','P','Axe/LH','Syn/Sem/\nLay','T/L/I %','Versions','USD','Seconds'],[
            [f"{r['run_id']} / {r['repeat']}",r['policy'],f"{r['axe']}/{r['lighthouse']}",'/'.join(str(v) for v in r['failed'].values()),'/'.join(f'{v:.0f}' for v in r['retention'].values()),r['evaluated_candidates'],f"{r['cohort_allocated_cost_usd']:.4f}",f"{r['seconds']:.1f}"] for r in group
        ],[46,23,42,43,66,43,45,50])
        paragraph('Syn/Sem/Lay denotes syntactic, semantic, and layout failure counts. T/L/I gives text, link, and image retention. USD includes equal allocation of the shared source assessment.')
        emit(r'\clearpage');sub(domain+' -- iterations and execution')
        paragraph('Paths list every evaluated version in proposal order. An asterisk marks the selected output. Gaps in proposal indices correspond to opportunities without an additional measured page.')
        trajectories=[]
        for r in group:
            attempts=r['attempts_detail']
            def path(metric):return ' / '.join(str(a['audit'].get(metric,'--'))+('*' if a['chosen'] else '') for a in attempts)
            steps=' / '.join(str(a['iteration'])+('*' if a['chosen'] else '') for a in attempts)
            trajectories.append([f"{r['run_id']} {r['policy']}-R{r['repeat']}",steps,path('axe'),path('lighthouse')])
        table(['Run / repetition','Proposal indices','Axe path','LH path'],trajectories,[73,103,101,101])
        sub('Requests, resources, and stopping')
        trace=[]
        for r in group:
            run='sql-run-'+str(r['run_id']);gen=[p for p in e.prompts if p['call']['run']==run]
            planning=sum(c['role']=='Planning / diagnosis' for c in r['calls_detail'])
            chosen=next(a for a in r['attempts_detail'] if a['chosen']);idx=chosen['iteration']
            selected_gen=[p for p in gen if p['call']['iteration']==idx]
            selected_request=selected_gen[-1] if selected_gen else gen[-1]
            trace.append([f"{r['run_id']} {r['policy']}-R{r['repeat']}",f"{len(gen)}/{planning}",f"{r['input_tokens']:,} / {r['output_tokens']:,}",f"Iteration {idx}; call {selected_request['call']['id'][:10]}\nSHA {selected_request['call']['request_hash'][:12]}",stop_label(r['stop_reason'])])
        table(['Run','Gen./P-D','Input/output tokens','Selected prompt','Stop condition'],trace,[57,42,77,108,94])
        paragraph('Gen. counts generation requests, including repeats within a proposal opportunity. P-D counts component planning or diagnosis. The selected prompt is identified by call and request-hash prefixes.')
        sub('Assessment coverage and shared resources')
        coverage=[]
        for policy in ('P1','P2'):
            gg=[r for r in group if r['policy']==policy]
            def span(k):
                v=[r['coverage'][k]*100 for r in gg]
                return f'{min(v):.1f}%' if min(v)==max(v) else f'{min(v):.1f}-{max(v):.1f}%'
            coverage.append([policy,span('Syntactic'),span('Semantic'),span('Layout'),f"{sum(r['cohort_allocated_cost_usd'] for r in gg):.4f}",f"{sum(r['cohort_allocated_tokens'] for r in gg):,.1f}"])
        table(['P','S coverage','M coverage','L coverage','USD','Allocated tokens'],coverage,[22,67,67,67,55,100])
        paragraph(f"The shared source assessment costs US${d['shared']['cost_usd']:.6f}, divided equally across six runs. Input/output tokens retain original ledger ownership; allocated tokens and USD use equal-share accounting. Coverage is the proportion of applicable opportunities with conclusive assessments.")
    emit(r'\clearpage');heading('Evidence references')
    paragraph('Each run links its frozen input, repair requests, ACT retrieval records, candidate measurements, and selected output. The same thirty-run cohort underlies the manuscript and this supplement.')
    table(['Source','Input SHA-256 prefix','Saved runtime digest prefix'],[
        [domain,next(r for r in e.rows if r['domain']==domain)['input_sha256'][:24], '\n'.join(sorted({r['manifest']['runtime_snapshot']['code_digest'][:24] for r in e.rows if r['domain']==domain}))]
        for domain in e.summary['domains']],[83,149,146])
    total_cost=sum(r['cohort_allocated_cost_usd'] for r in e.rows)
    table(['Record','Value'],[
        ['Cohort export','data/runs.csv'],
        ['Cohort SHA-256',sha(SOURCE.read_bytes())],
        ['Independent runs / evaluated versions','30 / 116'],
        ['Recorded generation requests',len(e.prompts)],
        ['Total allocated cost',f'US${total_cost:.6f} (US${total_cost:.2f} rounded)'],
    ],[120,258])
    emit(r'\end{document}')
    (source_dir/'main.tex').write_text('\n'.join(source)+'\n')
    return {'runs':len(e.rows),'evaluated_versions':sum(len(r['attempts_detail']) for r in e.rows),
        'generation_requests':len(e.prompts),'skills':len(e.skills),'allocated_cost_usd':total_cost,
        'source_sha256':sha(SOURCE.read_bytes()),'original_screenshot_artifacts':{d:e.domains[d]['preview']['artifact_id'] for d in e.summary['domains']},
        'selected_screenshot_artifacts':{str(r['run_id']):r['preview']['artifact_id'] for r in e.rows},
        'input_mode':'Portable CSV/JSON exports','integrity_checks':dict(e.integrity)}


def compile_pdf(source_dir, output):
    with tempfile.TemporaryDirectory(prefix='supp-e1-latex-') as temp:
        build=Path(temp)
        run=subprocess.run(['latexmk','-pdf','-interaction=nonstopmode','-halt-on-error','-outdir='+str(build),'main.tex'],cwd=source_dir,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        log=(build/'main.log').read_text(errors='replace') if (build/'main.log').exists() else run.stdout
        if run.returncode:
            raise RuntimeError(run.stdout[-10000:])
        warnings=[line for line in log.splitlines() if 'Overfull' in line or 'undefined' in line]
        output.parent.mkdir(parents=True,exist_ok=True)
        staged=output.with_suffix('.publishing.pdf');shutil.copyfile(build/'main.pdf',staged);staged.replace(output)
    from pypdf import PdfReader
    reader=PdfReader(output)
    return {'pages':len(reader.pages),'sha256':sha(output.read_bytes()),'bytes':output.stat().st_size,
        'latex_class':'acmart (same saved class as the TWEB manuscript)',
        'class_sha256':sha((source_dir/'acmart.cls').read_bytes()),'tex_sha256':sha((source_dir/'main.tex').read_bytes()),
        'warnings':warnings,'page_dimensions':[float(x) for x in reader.pages[0].mediabox]}


def stop_label(reason):
    if 'no effective change' in reason.lower() or 'ineffective' in reason.lower():return 'No effective change'
    if 'recorded_decision' in reason:return 'Continue/stop decision'
    if 'attempt' in reason.lower() or 'iteration' in reason.lower():return 'Proposal limit'
    if 'regress' in reason.lower():return 'Consecutive regressions'
    return reason.replace('_',' ')[:70]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HOME/'supplementary.pdf')
    parser.add_argument('--refresh-source',action='store_true',help='Regenerate main.tex from exported CSV/JSON evidence.')
    parser.add_argument('--receipt',type=Path,help='Optional external verification manifest.')
    args=parser.parse_args();result={}
    if args.refresh_source:
        result=write_source(load_evidence(),HOME)
    elif not (HOME/'main.tex').exists():parser.error('Run --refresh-source to create main.tex.')
    result.update(compile_pdf(HOME,args.output.resolve()))
    result.update(output=str(args.output.resolve()),source_dir=str(HOME),source_regenerated=args.refresh_source,
                  data_source='Portable CSV/JSON exports and thumbnail files; no catalogue access')
    if args.receipt:
        args.receipt.parent.mkdir(parents=True,exist_ok=True);args.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('original_screenshot_artifacts','selected_screenshot_artifacts')},indent=2))

if __name__=='__main__':main()
