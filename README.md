# ContCarSim data generator

Standalone generation of simulated paracetamol/ethanol slurry filtration and drying
recordings from [ContCarSim](https://github.com/CryPTSys/ContCarSim), pinned at
`7f620cbff705672155afc428bcc43281efcb775c`. The simulator and this distribution use
GPL-3.0; see LICENSE. No production data, credentials, engine code or dashboard code
are included. Default campaigns preserve upstream equations and built-in disturbance sizes. The sensitivity
campaign below explicitly scales disturbance sizes. The simulator uses the
reviewed `sensor-logging-v2` correction described below; it is modified upstream code.

## Measurement logging correction

The unmodified upstream logger repeats the last timestamp at cycle boundaries. Before
execution, the coordinator applies exact replacements in two logging routines from `patches/cycle-timing.json`
only when the original source hash matches. Logging starts at the next sample instant,
noise-free channels retain matching lengths, and filtration endpoints on the sampling grid
are preserved rather than deleted. Filtration equations and its completion condition remain unchanged. The campaign, job saved inside each native
MATLAB file, and manifest record the patch ID and original/modified file hashes.

The correction changes measurement-noise random consumption and the next-cycle filtrate
bias, so identical seeds do not reproduce unmodified recordings. Process equations and
built-in disturbance definitions are unchanged in logging-only campaigns. No exported readings are deduplicated,
interpolated, averaged or retimed. A fresh pilot must pass private validation.

## Hosted pilot without a personal MATLAB license

This repository must be public. MathWorks' official GitHub actions automatically license
supported MATLAB products for public workflows. Standard GitHub-hosted runners for public
repositories have free compute; artifact storage is subject to account allowances. No paid
runner or billing change is configured here. See [MathWorks licensing](https://github.com/matlab-actions/setup-matlab#licensing)
and [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

1. Enable Actions and manually run **Generate ContCarSim pilot**.
2. The Windows runner prepares MATLAB R2024b and calls the simulator with the documented logging correction
   for the counts and seeds frozen in `campaign.json`. No local MATLAB installation or Python engine
   is involved. Compatibility of the supplied Windows compiled components is established by
   execution, not assumed. Failures retain logs and partial outputs.
3. Download the `contcarsim-pilot` artifact within seven days. It contains `data/raw/contcarsim/pilot/`
   and `results/contcarsim/pilot/`. Use fresh local data/results directories for each attempt and preserve failed pilot outputs.
4. Run the private/local project's normal pilot evaluator. Native/CSV equality, original timing,
   three-lag fitness and pre/post-disturbance observations must pass before full generation.
   A small pilot does not establish detector accuracy or healthy-baseline sufficiency.

## Full campaign after verified pilot approval

The repository initially has no `approvals/pilot.json`, so full generation is blocked.
The local project's `scripts.contcarsim.package_hosted approve-pilot` command re-evaluates
the real downloaded pilot and produces a minimal approval file only on success. Commit that
file here. It contains hashes, three-lag gate approval and the exact GitHub pilot run ID, not
the private engine's code or full report. This is an explicit repository-owner attestation;
it cannot independently recompute a private engine's fitness rules on GitHub.

Manually run **Generate approved ContCarSim full campaign**, entering that pilot run ID.
The workflow verifies the downloaded pilot bytes and approval, estimates runtime from the
pilot, and generates 19 disjoint shards of ten recordings with at most four concurrent jobs.
Any failed shard blocks merging; original failed data is retained rather than replaced.
Each job has a six-hour limit; predicted compute above five hours per shard with 2x headroom
stops before full generation. Download `contcarsim-full` within seven days, then perform
the private/local project's full numerical and application acceptance checks.

## Data contract

One complete 1,800-second simulation is one independent recording, including startup and many
45-second carousel cycles. Sampling is one second, with at least 75 observations required.
The nine original measured channels are preserved at round-trip double precision:

| Channel | Unit |
|---|---|
| m_filt_WI101 — cumulative collected filtrate mass | kg |
| P_PI101 — compressor delivery gauge pressure | Pa |
| P_PI102 — filtrate gauge pressure | Pa |
| c_slurry_AI101 — slurry solids concentration | kg/m3 |
| L_cake_LI101 — cake height | m |
| V_slurry_LI101 — fed slurry volume | m3 |
| Tg_in_TI101 — inlet drying gas temperature | K |
| Tg_out_TI102 — outlet drying gas temperature | K |
| Vdryer_FI101 — inlet drying airflow | L/min |

No averaging, interpolation, additional noise, flow derivation or internal-state features.
Native `.mat` files remain separate from CSV inputs. `labels.csv` records the built-in
scenario and actual cycle-boundary activation; `quality.csv` preserves discharged-cake quality.
Nominal means no injected disturbance, not guaranteed acceptable product quality.
Cake resistance is unmeasured: downstream deviations alone do not verify that exact cause.

Full campaign: 100 reference nominal (30 fitting/70 calibration), 50 held-out nominal,
20 concentration ramps and 20 resistance steps. Seeds are fixed and disjoint from the pilot.
The manifest records source/config/wrapper checksums and per-recording native/sensor checksums.
No accuracy or fitness claim is implied by successful simulation alone.

## Explicit disturbance-size sensitivity campaign

When campaign.json selects sensor-logging-v2-disturbance-scale-v1, its checksummed
patch also parameterizes disturbances.m. The wrapper passes scenario and size explicitly;
scalar scenarios and size 1 retain the original disturbance equations. No process equation,
controller or noise distribution changes. This is modified upstream simulator source.

The sensitivity campaign generates 24 disturbed recordings: two seeds at each of six
sizes (0.25, 0.5, 1, 1.5, 2, 3) for both families. Concentration ramps end at increases of
10%, 20%, 40%, 60%, 80%, 120%; cake-resistance steps multiply resistance by
1.25, 1.5, 2, 2.5, 3, 4. Disturbances still start at the first cycle boundary after 300s.
Two matched nominal controls check compatibility; matched size-1 disturbed seeds also
check reproduction of earlier recordings. These repeated controls are not new independent
normal validation runs. All seeds and sizes are frozen before scoring. Original and partial
failed outputs are retained. A strength sweep is exploratory, not an accuracy certification.

The pilot workflow is the execution vehicle for this separate explicit sensitivity request;
it does not dispatch the approval-gated 190-run full campaign. Detector fitting, plots,
fitness checks and study reports remain private and are not part of this public package.
