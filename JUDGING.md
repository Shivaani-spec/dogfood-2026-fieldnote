# Assignment, scoring and normalization

## Assignment

The organizer chooses a target count of reviews per submitted project. The deterministic greedy allocator:

1. Reads a project's event track.
2. Removes judges already assigned to that project.
3. Keeps only judges whose judge_tracks include the project track.
4. Orders eligible judges by total event workload, then by a stable SHA-256 tie-breaker.
5. Assigns until the target is reached or the eligible pool is exhausted.

It never fills a gap by crossing tracks. Existing fixture assignments are preserved, so rerunning assignment generation only fills missing slots.

## Rubric

Each event owns criteria with positive weights. The organizer edits criterion keys, labels and weights; weights are normalized to sum to one. Judges submit a score in [1, 5] for every criterion. One assignment stores one replaceable ballot.

## Cross-judge normalization

For one criterion, let x[j,p] be judge j's raw score for project p. Calculate event mean μ and population standard deviation σ. For each judge, calculate mean μj, population deviation σj, and review count n. Reliability is r = n / (n + 5).

When σj > 0.20 and σ > 0:

    x'[j,p] = μ + (x[j,p] - μj) * (σ / σj) * r

For a judge with little or no score spread, avoid division by a near-zero deviation and shift toward the event mean:

    x'[j,p] = x[j,p] + (μ - μj) * r

Both branches clip to [1, 5]. The factor n/(n+5) shrinks estimates for judges with fewer observations toward their raw values. The organizer view and result endpoint expose event mean/deviation, judge means/deviations, counts and shrink factors.

For each project, average available adjusted ratings per criterion, then combine available criteria using configured weights renormalized over criteria that have ratings. Raw comparisons use the same weighted rule before adjustment. Unscored projects remain at the end of the leaderboard.

This is a transparent severity/spread adjustment, not universal statistical ground truth. Small or track-isolated panels produce noisy estimates, so reviewers should inspect raw and adjusted columns together. Judges cannot see peers' scores. Aggregates are organizer-only until publication, and publication is blocked while a configured community voting window is active.

## Community ballot

Each voter can set one credit amount per project, from one to four. The event budget is 16 quadratic credits: a choice c costs c squared and its influence is square root of c. Voters can revise their choice if the total remains within budget. Signed-in team members cannot vote for their own project. Audit records contain the project and credit amount, never the raw visitor cookie. Public responses do not expose counts until results are published.
