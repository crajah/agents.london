# Genotype schema migrations

*(BUILD consequent task: "adding a budgeted locus post-launch changes every
agent's expressed values; migrations must state the dilution and
re-baseline.")*

## The problem being governed

Expression is a **budget** (genotype-spec.md Rules 3.22–3.23a): every
budgeted locus receives a share of B = N/2, so ADDING a budgeted locus
dilutes every existing agent's expressed values by roughly N/(N+1) — a
silent, population-wide nerf that would corrupt every longitudinal
finding built on expressed values.

## The policy

1. **Dispositions and other OUTSIDE-budget loci may be added freely.**
   They do not touch the budget. (Precedents: Teleport Affinity, Survival
   Instinct — both landed outside the budget for exactly this reason.)
2. **A budgeted locus may only be added with a migration note in this
   file** stating: the new N, the dilution factor N_old/N_new applied to
   every expressed value, and the re-baseline date before which expressed
   comparisons across the boundary are invalid.
3. **Longitudinal analyses must partition at every migration date** listed
   below. The founding-centre discipline (genotype-spec 3.2b) applies: you
   control for the era, or the finding is void.
4. **Removal follows the same rule** in reverse (concentration instead of
   dilution) and is expected never to happen.

## Migration log

| Date | Change | Budget effect |
| :--- | :--- | :--- |
| (none since launch) | — | — |
