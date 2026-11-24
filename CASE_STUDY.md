# Case study: triage summaries for a supplier-vetting team

One idea, taken all the way: the summary is a **triage note**. Its job is to tell the reader in about 30 seconds
whether a company is worth a closer look, so it leads with risk signals, has the same shape every time, and every
number in it must be traceable to the record. Plain Python computes the red flags first. Those flags feed the prompt
and also serve as the answer key for scoring.

All numbers below come from [`results/eval_report.md`](results/eval_report.md), produced by
`uv run python -m evaluation.run`. Scoring runs offline from cached responses.

## 1. What a good summary is for this team, and why

The reader vets suppliers and partners. They decide whether to look closer, drop the company, or ask a specific
question. They will read the full record later if the company goes ahead. Two costs are lopsided:

- **A missed red flag is expensive.** It can mean signing a supplier that is being wound up or is losing a court case.
  A missed nice-to-know fact costs almost nothing.
- **One invented number destroys trust.** If the reader catches one wrong figure, they have to re-check every summary
  against the record, and the summaries stop saving time.

So a good summary is, in priority order:

1. **Faithful.** Every number and fact can be found in, or computed directly from, the record. No outside context and
   no guessed causes.
2. **Complete on red flags.** Every material flag that applies is mentioned, with its key number.
3. **Honest about gaps.** When there are no statements, only one year, or a missing year, the summary says so and
   describes no trend.
4. **Short and fixed in shape.** About 80 to 150 words, always in this order: Verdict, Key risks, Financials, People and
   ownership, Data gaps.
5. **Plain.** RM amounts with units and no filler.

The red flags are 19 rules in three severities. Examples: a status other than Active; being the defendant in a
winding-up petition; any non-clean audit opinion in any year; negative equity; judgments entered against the company;
pending cases against it; a net loss; revenue down 10% or more; negative operating cash flow; a quick ratio below 1.0;
interest cover below 1.5 or debt service cover below 1.0; liabilities above 2x equity; no financial statements. Recent
director appointments, a recent name change, a young company and data gaps are context. Only cases where the company
is the **defendant** count as risk. The triage level follows from the flags: any high flag means **High concern**, any
medium flag **Review**, otherwise **Low concern**. "Recent" is measured from the record date, 31 December 2025.

Some things the data does not allow, and the definition says so: shareholder changes (shareholders have no dates),
director departures (only current directors are listed), and anything after FY2024 (no company has FY2025 figures).

The full definition, the flag table, the thresholds and the rubric are in
[`docs/definition_of_good.md`](docs/definition_of_good.md). It was committed before any prompt or model call (the first
commit after the template). Its change log lists every later change to the evaluation code, and why.
Aaron read the definition and accepted it without changes before the review below.

## 2. What you built

```
data/companies.jsonl
   │
   ├─► summarizer/facts.py   plain Python: red flags, triage level, key numbers per company (the facts sheet)
   │         │
   │         ├─► prompt (v2, v3)            summarizer/prompts.py
   │         └─► answer key for scoring     evaluation/
   │
   ├─► summarizer/generate.py   builds the prompt, calls the model through a disk cache (summarizer/llm.py)
   │         └─► runs/<version>/<company>__<request hash>.json   every raw response, kept
   │         └─► summaries/<version>.jsonl                       one line per company, read by the viewer
   │
   └─► evaluation/run.py   scores every version offline ─► results/eval_report.md, results/eval_details.json
```

**Versions** (all run on the same model, all 50 companies):

| Version | Input | Instruction |
|---|---|---|
| v1 (baseline) | raw record (JSON) | "Write a short summary for the vetting team so they can decide whether it is worth a closer look." |
| v2 | raw record + facts sheet | fixed five-part structure, 8 rules (only facts from the sheet or record, copy numbers as written, verdict = computed triage level, every high and medium flag with its number, say "no data", 80 to 150 words) |
| v3 | same as v2 | one change: the Financials line in the template spells out each label (`revenue RM <x>, profit after tax RM <x>, ...`), because 12 of 47 v2 Financials lines listed bare numbers such as "RM 19.37m, RM 473.2k, RM 12.32m, 1.49" |

**Engineering choices**

- **The model writes, code decides.** The facts sheet decides what counts as a red flag and what the verdict is. The
  model only turns it into readable text. A model can still drop or invent things, and the evaluation checks for that.
- **Cache everything.** A request is hashed (model, messages, settings) and its response saved under `runs/`. A cached
  request is never sent again, so scoring and rebuilding the summaries need no key
  (`uv run python -m summarizer.generate --offline`). Empty or truncated responses are not cached as successes.
- **Free-tier limits.** A per-day 429 stops the run at once instead of retrying. Companies run in pairs (every version
  for one company before the next), with the ten manual-review companies first. If the cap had hit mid-run, the result
  would still have been a complete paired sample.
- **Post-processing.** The only step between a raw response and the summary line is `normalise`: strip a wrapping
  code fence and replace em dashes. Raw responses stay untouched.
- **Tests.** 17 tests use hand-written dummy summaries, one faithful and one with planted errors, to check the facts
  sheet, the number extractor, unit and rounding tolerance, the negative control, flag patterns, negation,
  contradictions and structure (`uv run pytest`).

**Provider and model.** Google AI Studio (Gemini API, free tier) through its OpenAI-compatible chat-completions
endpoint. Model `gemini-3.5-flash-lite`; the `model` field in every response says the same. Temperature 0,
`max_tokens` 4096, the model's default thinking. 150 calls (3 versions x 50 companies), about 451k tokens in total
(396k of them prompt tokens). An earlier partial run on `gemini-3.5-flash` stopped at 17 responses: the free tier
allows 20 requests per day for that model, and the quota error reported it as `gemini-3.6-flash`. Those responses are
kept in `runs_superseded/` and are not scored. Mixing two models would have made the comparison meaningless, so every
version was re-run on one model.

**Reproduce**

```bash
uv sync
uv run python -m summarizer.facts                  # flag table for all 50 companies
uv run python -m summarizer.generate --offline     # rebuild summaries/*.jsonl from runs/ (no key needed)
uv run python -m evaluation.run                    # write results/eval_report.md
uv run pytest
```

## 3. How you know whether it's good

Each part of the definition has its own check. The checks are automatic unless marked otherwise.

| Check (part of the definition) | v1 | v2 | v3 |
|---|---|---|---|
| Numbers checked (money, percent, ratio) | 909 | 477 | 506 |
| Untraceable numbers (faithful) | 2 (0.2%) | 0 | 0 |
| Negative control: numbers traceable against a **different** company's record | 12.1% | 13.8% | 15.2% |
| Red-flag recall, high + medium (complete) | 68/86 (79.1%) | 85/86 (98.8%) | 86/86 (100%) |
| Red-flag recall, high only | 14/14 | 14/14 | 14/14 |
| Summaries mentioning every material flag | 34/50 | 49/50 | 50/50 |
| Context flags mentioned (recent directors, name change, data gaps) | 37.5% | 55.0% | 62.5% |
| Contradiction hits (for example "no litigation" when the company is a defendant) | 0 | 0 | 1 (false hit, see below) |
| Verdict matches the computed triage level | no verdict stated | 50/50 | 50/50 |
| Words, median (min to max) | 309 (151 to 391) | 84.5 (58 to 151) | 91.5 (61 to 146) |
| Within 80 to 150 words (short) | 0% | 58% | 80% |
| Five-part structure present | 0% (not asked) | 100% | 100% |
| Financials line labels its numbers (added after reading v2) | n/a | 35/47 | 47/47 |

**What the numbers say**

- **The baseline is faithful, but it is not a triage note.** v1 rarely invents numbers. Of its two untraceable
  numbers, one is correct ("over RM680k" of pending claims, which total RM 681,600). The other is a loose
  approximation ("~60%" for a 58.7% margin). But it runs 151 to 391 words, gives no consistent verdict, and misses
  a fifth of the material flags. It says nothing about debt service in 8 of the 16 companies where that flag applies.
  It misses high leverage in 6 of 9, and in at least 4 of those it gives the ratio without calling it high. For
  SYN-001203, which has no financial statements, v1 answers "Worth a closer look? Yes" and calls it "a well-established
  player" with no word about the missing financials. The other two such companies get a note, worded in a way the
  patterns did not catch. 5 of 50 v1 summaries also add advice nobody asked for (advance payments or cash on
  delivery).
- **v2 fixes completeness and shape.** It has one material miss: SYN-000657, where it wrote "Quick ratio 0.91" and
  dropped "below 1.0". But 12 of 47 Financials lines listed unlabelled numbers.
- **v3 fixes that one failure** without losing anything the checks measure: 47/47 lines labelled, 86/86 flags, and 80%
  within the length band.
- **v3 is the version I would ship**, with the limits below.

**How far to trust each check**

- **Recall and verdict agreement are partly true by construction for v2 and v3.** Both versions see the facts sheet
  they are scored against, so a high score mainly shows that the model copies the sheet faithfully. That has value,
  since a model can drop flags, but it is not independent evidence that the flags are the right ones. Only v1's recall
  is an independent measurement of what a model notices unaided.
- **The number checker is lenient by design, and the negative control measures the cost.** Each summary is also
  scored against the next company's record, and 12 to 15% of its numbers still "match" (11.9%, 13.1% and 13.5% if
  the rule thresholds "1.0", "1.5" and "10%", which match for every company, are left out). Each record has hundreds
  of values, and rounded numbers often coincide. So a wrong number has roughly a 1 in 8 chance of passing. Zero
  untraceable numbers in v3 is strong evidence of faithfulness, not proof.
- **Hand checks (done by the Claude Code agent that built the system, not by Aaron).** Samples are drawn with a fixed
  seed (`uv run python -m evaluation.handcheck`), and the judgements are in `results/handcheck_*.csv`.
  - **Untraceable numbers.** The first checker run flagged 22 numbers in v1 (2.4%). The agent judged 21 of them
    correct (checker false alarms) and 1 unclear ("~60%" for a 58.7% margin); none was a real error. So that checker
    had a false-alarm rate of about 95%. The main cause: the model **truncates** rather than rounds (320,578 written
    as "320k"; 14 cases). The rest were LaTeX amounts, a date written as 20.11.2017, and correct sums the checker did
    not know about. The checker was then fixed (disclosed in the definition's change log), which left 2 flagged in v1,
    the same two judged above (one false alarm, one unclear). v2 and v3 had nothing flagged, so their false-alarm rate
    cannot be estimated. v3 was not in the hand-check samples (it was generated after they were drawn).
  - **Traced numbers.** 30 numbers the checker accepted (15 from v1, 15 from v2) were checked against the field it
    matched. All 30 were right. In 3 the match was to a different field with the same value (for example profit before
    tax equal to profit after tax).
  - **Flag patterns.** Of 24 sampled keyword hits, all 24 were real mentions, though one matched "low" inside "flow"
    (a bug, now fixed) and was right by luck. Of 13 sampled misses, 8 were true misses (7 in v1, 1 in v2). In the other
    5, v1 described the issue in a way the strict patterns do not count. Examples: "leverage ratio of 2.10" with no
    judgement word, and "debt-servicing capability remains relatively tight". Outside the sample, two of v1's three
    "no financial statements" misses are worded the same way ("financial statements are currently unlisted"). So v1's
    true recall is somewhat higher than 79%, and v1 is the version the strict patterns treat worst.
  - **Contradictions.** v3's one hit, on SYN-000545 ("winding-up status and active insolvency petitions"), is a false
    hit by the pattern, not a contradiction.
- **What no automatic check sees.** Soft claims with no number: "stable finances" (SYN-000029) is the model's judgement,
  and 19 v3 summaries use words like stable, healthy or strong. Also usefulness to a real reader. That is what the
  manual review is for.

### Manual review

Ten companies were picked in advance from the facts sheet, before any generation: 2 clean, 3 litigated (one of them
winding up), 2 loss-making, 1 non-clean audit, 1 with no financial statements, 1 young company
(`docs/manual_review_plan.md`). Each has a v1 and a v3 summary, labelled A and B in random order
(`docs/manual_review_sheet.md`), scored 0 to 2 on faithful, red flags, verdict and readability.

**Who scored it.** The first pass was done by a separate Claude agent that had not built the system and could not
see the version key, the case study or the automatic results; it checked each summary against the raw record. Aaron
then reviewed all 20 scores and notes against the records and agreed with them. So this is an agent review with a
human check, not an independent human panel. The blinding is weak, because v1 is three times longer and easy to spot.

| Version | Faithful | Red flags | Verdict | Readable | Total (of 8) |
|---|---|---|---|---|---|
| v1 | 1.20 | 1.50 | 1.50 | 1.10 | 5.30 |
| v3 | 1.80 | 2.00 | 2.00 | 2.00 | 7.80 |

What the review found that the automatic checks did not:

- **v3 still makes factual errors that are not numbers.** On SYN-000545 the verdict says "active insolvency
  petitions", but both petitions are closed (withdrawn, and judgment entered). On SYN-000785 it calls two 2023
  appointments "recent", outside the 12-month window. The number checker passed both, because every number in them
  is right. This is the clearest case for a check on dates and case status, not only on numbers.
- **v1's errors are mislabelled or wrong figures and a misleading tone.** It called a quick ratio the current ratio
  (SYN-001389), said operating expenses exceeded revenue when they did not (SYN-000785), filed two lost judgments
  under "resolved" (SYN-000397), and praised a company with no financial statements as "well-established"
  (SYN-001203).
- **v3 never got the verdict wrong** on these ten; v1 leaned positive on two High or Review companies.

Scores and notes: `docs/manual_review_sheet.csv`; unblinded summary: `results/manual_review_results.md`
(`uv run python -m evaluation.manual_score`).

## 4. What you'd do next, and how you'd keep improving it

**What's left, honestly**

- **The definition has not been tested with the real team.** The flags and thresholds (quick ratio 1.0, interest cover
  1.5, revenue down 10%) are textbook rules of thumb. The first thing to do is sit with two or three vetting analysts,
  show them ten summaries, and ask what they would have wanted first. I would also ask whether "Review" for 26 of 50
  companies is too many to be useful; that count is mostly driven by debt service strain.
- **Is the model needed?** v3 mostly re-words the facts sheet. The next experiment is a **pure template** (no model)
  scored with the same checks. If it scores as well and readers like it as much, the model is only worth its cost and
  risk for the parts a template cannot do. That might be summarising a long litigation history or explaining unusual
  combinations, such as SYN-000545, which is being wound up but profitable.
- **Small known defects in v3.** It sometimes copies the facts sheet's "[medium]" tags (2 summaries). The People line
  spends words listing placeholder names ("Director 1, Director 2, ..."). Some soft adjectives are not backed by a
  rule.
- **The length floor may be wrong.** 10 of 50 v3 summaries are under 80 words (61 to 75); 6 of them are Low concern. A clean company
  probably deserves a short note, so I would make the floor depend on the number of flags rather than force filler.
- **One model, one sample.** Everything ran on one model, once, at temperature 0. I have no measure of run-to-run
  variation or of how another model would do. Repeating v3 with a second free model on the same 50 companies is cheap
  and would show whether the prompt or the model drives the results.
- **Measurement changes after seeing outputs** are listed in the definition's change log: the MYR fix, the decimal
  point fix, the checker fixes after the hand check, and the new Financials-label check. Each one fixes how something
  is measured. None widens what counts as a hit, but they were made after seeing the outputs.

**How I would keep improving it**

1. **Gate every summary in production.** Run the number check and the flag recall check on each new summary before
   anyone sees it. If a summary has an untraceable number or misses a high flag, regenerate it once, then fall back
   to the template.
2. **Keep a regression set.** The ten hand-reviewed companies, plus every company where a reader reported a problem,
   become fixed tests. A prompt or model change ships only if it does not lose on them.
3. **Use reader feedback as the ground truth.** A thumbs up or down and a "what was missing" box in the viewer turn
   the team's judgement into labels. Those labels can tune the flag rules and test whether an automatic judge
   (a second model scoring soft claims) agrees with people before it is trusted.
4. **Watch the data.** New fields (for example dated shareholder changes) or new audit opinion wording would
   silently weaken the rules. The facts sheet should fail loudly on values it has not seen before.

## AI tools used

The code, experiments and first draft of this case study were produced by Claude Code (Anthropic) agents working
under Aaron's direction. Aaron set the task, accepted the definition of a good summary,
and reviewed the agent's scoring of the ten review companies. The first pass of that review was also done by a Claude
agent (a separate one that had not built the system). The summaries themselves were written by `gemini-3.5-flash-lite` as described
above.
