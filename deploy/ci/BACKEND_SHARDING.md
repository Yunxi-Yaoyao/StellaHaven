# Backend CI budget split (validation only)

## CI182: exact-source pure-container clone and measured cohort replacement

`ci182-backend-timings.json` retains all 106 complete successful original
intervals, unchanged. The runner now consumes those observations as well as
CI178/older floors. Only nine completed source-evidence commands use the
explicit `copy-capacity-timings.json` replacement cohort; every unrelated floor
is retained. Each local replacement keeps `ceil(1.20*t+5)`. Source metadata,
reads/hashes, original case IDs and all production loader bytes are unchanged.

Seven source-isolated current-before/current-after whole-command pairs are
retained, plus complete CI182 baselines and current whole after executions for
completion/contract. Their original sources and collected IDs are frozen;
collection is not reported as a local-before execution. The final exact-type
identity hardening is separately bound and four complete original commands are
repeated on that exact source. No profiler speed ratio or global multiplier is
used. Full mounted OpenAPI and ordered declarations compare equal.

The unchanged setup-aware LPT plan, seven slots, 75/140s setup and all argv now
model **1086.000..1087.000s**; the original measured-cost countercheck is
**886.326..995.991s**. The 1100/1000s gates and effective 1200s runner cap are
unchanged. The earlier eight-command cohort passed 1100s but failed 1000s;
only the complete owning contract command observation closes that second gate.
Renderer/verifier bind both CI182 and the new cohort metadata, including stale
binding negatives. No active YAML, runner configuration, concurrency, image,
installer, production code or deployment rule changes.

Detailed provenance, native XML/logs, failed exploration and the full compressed
schema equality artifact: `docs/private-remediation/copy-capacity-final/`.
These are local/mixed observation models, not a newly executed remote pipeline.

## fnOS and stdlib protocol regression additions

The227-command inventory adds55-case auto configuration and nine stdlib
end-to-end protocol cases plus the16-case fnOS source gate. Parent completed
local observations are recorded in owned-timings.json with their actual boundary;
the source-only gate is a Python3.13 host run, not remote CI. No completed cost
is lowered. Setup-inclusive seven-way estimates are1098.306..1099.247s:
the explicit model reserve is now100s against the unchanged1200s runner cap.
The CI178-measured replay<=1000s countercheck, exact argv inventory, all
business assertions, seven shards and runner resources remain unchanged.
This is not a claim that the expanded remote pipeline already passed.


## CI178: recalibrate the same seven shards from completed remote intervals

The current inventory has 225 unique original argv (including all new root-Agent
and file-config tests). CI178 completed six backend shards; shard 4 exhausted
its unchanged 1200s cap. Two API evidence files still had the 10s fallback weight
but actually completed in 214.222s and 198.255s. This was a load-model defect,
not a reason to skip either file or enlarge the runner timeout.

`ci178-backend-timings.json` freezes 196 successfully completed command intervals
from the exact CI178 source. Failed/censored and skipped-only commands are not
called completed timings. Each new floor is `ceil(1.05*t)`, taking the maximum
with all older floors and reserves. No runtime learning or cache writes occur.
The same setup-aware LPT algorithm now models all seven shards at <=1080s,
including 75s common and optional 140s browser preparation: a current 10% reserve
against the unchanged 1200s cap. The earlier 20% model is preserved below as
history, not asserted for the expanded workload. Replaying the measured costs
on the new assignment is <=1000s for each shard; neither is a future guarantee.

No `.gitlab-ci.yml`, shard count, runner resources, timeout, dependency installer,
application code, migration or business-test assertion changed. The complete original
command Counter and per-process fail-fast dispatch remain mandatory. Renderer
binding includes the calibration input, including missing/corrupt negatives.

## Historical Nav/Files adaptation: seven mandatory budgets

The d0592d3 inventory has 200 original argv. The additive owning inventory
adds all 18 Files test files (218 commands total), and dispatches the eight
already-discovered Nav/shared-media PG files through strict CI-owned nonce
admission. Execution/setup share discovery; unrelated PG opt-ins stay off.
See [the fixture, cleanup and manual boundary](../../docs/nav-files-nonprivileged-ci-20261023.md).

All 26 completed new suite observations are frozen in `owned-timings.json`;
use `ceil(1.5*t+5)` including per-file PG lifecycle, without lowering the older
CI170 floors/reserves. With the original 75s/140s setup charges, six shards
model 1050.241s, seven 911.035s, eight 789.108s. Seven is the smallest measured
model retaining the <=960s headroom gate. These are not remote CI runtimes.
The effective 1200s cap, three runner slots, 25m YAML, resources and deployment
rules are unchanged. Existing strict active/rendered YAML negatives continue
rejecting wrong counts; renderer binds the new runner/admission/inventory too.

The historical six-shard discussion below is preserved as historical evidence,
not the current inventory/budget or a claim that all original commands were
rerun locally. Local original-image replay covered the actual new Files/Nav
cohorts and owning CI tests, not a fresh complete remote seven-shard pipeline.

## CI170: six independent budgets, not more concurrent resources

`backend-test: parallel: 6` retains the exact original command multiset: six grouped pytest invocations plus every sorted `tests_isolated/test_*.py` file (189 unique commands at the reviewed source). New files are discovered automatically. Every command still runs in its own fresh Python/pytest process with its original arguments; the first nonzero exit stops that shard. `build-images.needs: backend-test` requires **all six** instances. No test deletion, new skip/xfail or `allow_failure` is introduced.

The YAML backend timeout remains **25m**, but the existing test runner's effective `maximum_timeout=1200` is **20m**. This change does not edit the runner service/configuration/concurrency (three), job resources, images, dependency installation or PostgreSQL bootstrap. More independent jobs can queue behind the same three execution slots. A branch pipeline expands from four backend + five other jobs (9) to six backend + five other jobs (**11**); it does not enable any deploy job.

### Frozen estimate selection

CI170 `ae489f8` job966 hit the effective 20m cap at 1202.932580s including cleanup. Its 52-command plan reached only command 21, `tests_website_settings`, which remained unfinished after >110s (old estimate 10s). Job967 stopped on the separately repaired canary interpreter fixture, so only its executed prefix can be measured. Jobs968/969 completed in 954.163923s / 1126.543895s. In aggregate, 135 successful full command intervals are observable; 54 commands lack a successful complete interval. Failed and unfinished commands are not recorded as successful timings.

Complete command-to-next-command timestamp intervals include interpreter startup/teardown. Use `ceil(1.05 * interval)`, retaining larger previous estimates **except** documentation: job968 finally completed that formerly censored command in 22.710521s (1 passed; pytest 21.41s), so its provisional 450s reserve is replaced with 24s. No other prior estimate is lowered. Unfinished website settings receives an explicit **uncertain 240s reserve**, not a claimed measurement. Remaining 24 default-weight commands receive 10s each (240s total); the total budget for all 54 unobserved-success commands is 406.592s, including that reserve and prior estimates.

The same deterministic setup-aware LPT algorithm charges **75s common setup** plus **140s once** when a shard contains unconditional browser commands. Execution and browser preparation use the same plan and file/directory predicate. Only the legal shard-count loops are generalized to GitLab's 1..200 range; argv/path and shard-index tie breaking are unchanged.

| Shards | Maximum modeled completion, including setup | Decision |
|---|---:|---|
| 4 | 1287.978s | Exceeds the effective 1200s cap |
| 5 | 1049.000s | Less than the required 20% headroom |
| 6 | 914.000s | Smallest tested count meeting <=960s |

All counts 1..6 were programmatically evaluated. The six-shard modeled maximum leaves 286s (23.83%) below 1200s. These are **uncertain mixed-source estimates**, not measured new-shard runtimes or a wall-clock guarantee: defaults, opt-in/guarded PG skips, settings censoring, downloads and shared resource variability remain. Only the next real complete CI can verify the 20m result. There is no push, remote pipeline creation or production deployment in this acceptance.

Evidence: workstation record `2026-10-23-stella-production-feedback/ci170-shard-capacity-fix/` contains original traces, interval parser, per-command observations, original-vs-new Counter comparison, independent LPT/browser oracle, 1..6 models, RED/GREEN logs and report. Mandatory local-ha discovery owns the capacity regression, real CLI child-argv/fail-fast audit and strict active/rendered CI guards. Renderer source binding still hashes the exact planner and setup shell; no real allowlist/inventory is rewritten.

## Historical context

The first unmodified [pipeline142](https://gitlab.xiya.live/yaoyao/StellaHaven/-/pipelines/142), commit `87774a430d0f2364d6538483596fdf30176058ba`, exhausted the former 15-minute backend timeout. The first four-way split used round-robin isolated files, with grouped commands on the first shard. Later setup-aware LPT balanced all commands, and YAML grew to 25m, but it could not override the runner's 20m cap. CI168's censored documentation interval initially required a conservative reserve. CI170 supplies the first complete replacement measurement and demonstrates that workload growth still needs more independent per-job budgets.

Frontend/experience deadlines, production helpers, protected master/manual deployment rules, READY gate, paused deployment eligibility and build dependency gates remain unchanged. Offline contracts do not establish production behavior, runner trust or a green remote pipeline.
