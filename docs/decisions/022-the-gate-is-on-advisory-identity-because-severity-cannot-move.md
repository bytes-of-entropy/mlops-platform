# 022: The gate is on advisory identity, because severity is a number that cannot move

- **Date:** 2026-08-30
- **Status:** accepted
- **Component:** `supply/`, `sbom/`, `Makefile`, `make.ps1`
- **Milestone:** M1
- **Extends:** record 019 (the exceptions mechanism), record 021 (the base bump)

## Context

Record 021 spent the cheap lever. Every pulled reference moved to the newest release in its current
major line, findings fell from 5,017 to 3,372, and what remains is the residue:

| | rows | unique advisories | with a fix available |
| --- | --- | --- | --- |
| Critical | 138 | 62 | 48 |
| High | 870 | 366 | 326 |
| everything | 3,372 | 1,054 | 2,121 |

`--fail-on high` meets 1,382 rows. It will meet them on the next run and the one after, because the
fixes that exist are mostly in majors this spine has good reasons not to cross yet — Postgres 17 will
not start against a `PGDATA` initialised by 16, Airflow 3 changes the compose topology, and record 021
argues each. A gate that fails identically every time is a gate people learn to ignore, and then it is
worse than nothing, because a red build that means nothing also hides a red build that means something.

Record 019 built the exceptions mechanism for a finding somebody read and argued for, and wrote down
its own limit: more than a handful and the base images are the problem. That trigger fired at 1,382 and
record 021 acted on it. What is left over is not a set of decisions anybody could make one at a time.

Three further facts constrain the answer, and two of them were learned rather than assumed.

**A scan result is a function of three things and only two are pinned.** The SBOM is now provably
reproducible — record 019's fifth-run note has six byte-identical inventories across two runs. The
scanner is pinned by digest with an expiry (record 020). The vulnerability database changes daily, by
design, because freshness is the entire point of it. So any gate defined on the *output* of a scan moves
when the database moves, whatever shape that gate has.

**Severity is not stable either.** Advisories get rescored. A finding that was Medium yesterday can be
High today with no change to any image, which means a count of Critical-and-High drifts for a second
reason unrelated to the first.

**A count cannot say what happened.** `apache/spark` is the case that settles this: between the two
runs its findings fell 46% while its Critical rose from 5 to 9 and its High from 93 to 121. A gate
reading a total would have called that image improving while the count that would actually stop a build
nearly doubled.

## Decision

**The gate is on advisory identity.** For each image, the advisory identifiers present at
Critical-and-High when measurement started are committed to `sbom/<image>.known.txt`, one per line,
sorted. A scan fails on an identifier that is not in that file. `supply/findings.py` is the comparison;
it reads grype's JSON rather than its table, because parsing a table means owning a column layout
nobody promised.

Three properties follow, and they are the reason for this shape rather than a count:

1. **The alert names what changed.** A rising number tells you a number. A new identifier tells you
   which advisory, in which image, and the table printed beside it names the package and the fixed
   version. A gate nobody can act on gets switched off.
2. **It cannot hide a swap.** One fixed and one new leaves a count unmoved. A set notices.
3. **It is not a set of accepted risks.** This is the distinction that matters most and the one a reader
   will get wrong first. `security/exceptions.toml` holds findings somebody read and argued for, and
   record 019 requires a reason of at least forty characters and an expiry date for each. A line in a
   baseline claims something weaker and entirely different: *this advisory was already here when the
   baseline was taken.* No judgement, no reason, no expiry, and no exception granted. Every generated
   baseline carries that sentence in its own header, because the two files look alike in a directory
   listing.

**Disappearance is not a failure.** An advisory that goes away is good news, reported and not gated.
Failing on it would mean a fix costs a commit before the build is green again, which is how a gate
teaches people not to fix things. The same applies to an advisory rescored *below* the gate.

**Medium and below are reported and not gated.** At 1,483 Medium findings a baseline over everything
would be four times the size and would fire constantly on advisories nobody would act on. `GATED` names
the two severities in one place, in the module that does the comparison.

**A missing baseline is an error, not an empty set.** Empty sounds safe and is not: every advisory would
read as new, so the failure would be hundreds of lines of "new advisory" when the actual problem is one
line long — this image has never been scanned. The message says which.

**Moving a baseline is a separate target.** `make scan-accept` rewrites every baseline from the current
scan and says so. It is not a flag on `scan`, because a flag is one keystroke from accepting whatever
appeared, and the whole value of accepting is that somebody reads the diff. A test asserts `scan` cannot
accept.

**`scan-report` replaces the report-only escape hatch.** `SCAN_FAIL_ON` is gone: it set a severity
threshold, and severity is no longer what gates, so it would have been a knob wired to nothing. What it
was actually used for — see the whole finding table without a gate stopping at the first hit — is now a
named target that both entrypoints carry, and `scan` is defined as that target plus the comparison.

## Alternative rejected

**Per-image, per-severity count ceilings.** Twelve numbers, a tiny file, and it handles the Spark case a
total would miss. Rejected because a count cannot name what changed, so every firing costs a manual
diff of two scans to find out what happened, and because it is blind to a swap. The file being small is
the only advantage and it is not one that matters: the baselines total 428 lines and are generated.

**Gate on fixable Critical only.** 48 advisories, small enough to review individually, and actionable by
construction since each names a fixed version. Rejected because it drops 326 fixable High findings, and
record 019 already argued that High findings in a base image are exactly the ones that turn out to
matter. It also cannot be driven to zero without crossing majors, so it is a gate that stays red for the
same reason `--fail-on high` does, just more quietly.

**Write exceptions for the residue.** Rejected in record 021 at 1,382 and no more attractive at 428. It
would also destroy the mechanism it used: an exceptions file with hundreds of entries is not reviewable,
so the property that makes an accepted finding mean anything would be gone on first use.

**No gate; publish and upload.** Honest, and the option with no false alarms. Rejected because the
repository already publishes the numbers — record 021's table, the committed inventories — so the marginal
thing a gate adds is precisely the part this option declines to do: notice a change without being asked.

**Pin the vulnerability database so the gate stops drifting.** This would make the gate perfectly stable
and perfectly useless, for the reason record 020 spends a whole record on: a scanner is only as good as a
database that must be fresh, and this repository has already been bitten once by a database that was 24
weeks old. Drift is the cost of the tool working.

## Prediction (recorded before the evidence)

1. `make scan-accept` writes six baselines totalling **428 unique advisory identifiers** — 62 Critical
   plus 366 High, deduplicated within each image but summing across images, so the file total is higher
   than 428 while the union is 428. Confidence: moderate on the per-file numbers, high that the union
   matches, since both come from the same parse of the same run.
2. The first `make scan` after accepting passes on all six images. Confidence: moderate. It should be a
   tautology — accept then compare the same scan — and the reason it might not is a database update
   between the two runs, which is exactly the drift this record documents. If it fails, the failures are
   advisories published in the interval and that is the mechanism working.
3. The identifiers my table parse produced and the ones grype's JSON produces agree, except possibly for
   one or two rows lost to terminal wrapping in the pasted output. Confidence: moderate. Two rows were
   visibly truncated in the fourth run's paste and one had an unreadable severity, so a small
   disagreement is expected and its direction is safe: a missing baseline entry fails the gate rather
   than passing something silently.
4. Within three months, this gate fires at least once for a reason that has nothing to do with any change
   in this repository — a newly published advisory against an unchanged image. Confidence: high. That is
   the designed behaviour and it is worth predicting so it is not mistaken for a defect when it happens.

## Deciding evidence

`make scan-accept` on a machine with a daemon, the six baselines committed, and then a `make scan` that
passes. Until the baselines exist, `scan` fails with "this image has no baseline", which is the correct
behaviour and not yet a demonstration of anything.

## What would change my mind

If prediction 4 turns out to fire *often* — several times a month rather than occasionally — then
Critical-and-High is too wide a net for a repository nobody is paid to watch, and the honest response is
to narrow `GATED` to Critical and say why, rather than to widen the baseline every time it fires. The
distinction to watch is whether the firings are ever acted on: a gate whose every firing is answered by
`scan-accept` has become a changelog with a red light attached.

## Consequences

The repository now has two files that look alike and mean different things, and one of them is generated.
That is a real cost in a directory listing, paid down by a header in every baseline that says which it is
and points at this record.

It also has a gate that can fail for reasons outside the repository. That is new here: every other check
in this suite is a fact about these files. This one is a fact about the world, and the world changes
without asking.

**What this does not do.** It does not make the images safer. 3,372 findings are still there and the
baseline is a record of them, not a reduction. What the gate buys is that the 3,373rd gets noticed, which
is the only claim being made and is worth stating so nobody reads a green build as a clean bill of health.
