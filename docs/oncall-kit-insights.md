# What the on-call kit contributes

Studied from Anthropic's [oncall-kit](https://github.com/anthropics/oncall-kit) at commit `c03282cd5381a5a2e12e32bfb3c8957d52ce01f1` on 2026-09-29. Read the README, standing rules, triage procedure and replay evaluation. This repository uses original implementation and prompt wording, informed by the reference. It does not install or execute the kit's Slack setup workflow.

## Ideas applied in this build

| Reference idea | V1 application | What to show |
|---|---|---|
| Detection remains deterministic | Cloud Monitoring triggers Pub/Sub; the model does not decide whether traffic crossed the alert threshold | Alert policy beside the incident |
| Evidence before explanation | Fixed tools return actual logs, metrics and deploy events with timestamps and links | Open one evidence item before accepting the diagnosis |
| Missing signals are unknown | Empty/stale metrics and failed tool calls are explicitly described as gaps | Explain why no data is not a green dashboard |
| Reconsider on pushback | The prompt asks the agent to test alternative hypotheses | Ask whether the deployment is merely correlated |
| Verify the original failure | Recovery discussion must check checkout and the triggering signal | /health is still green while checkout is broken |
| Humans own closure | Only a user action closes an incident | Enter what you actually did in resolution notes |
| Memory has provenance | Lessons are human resolution notes linked to incident IDs | Show the next investigation receiving the previous lesson |
| Validate independently | Automated contract tests are separate from live diagnosis evaluation | Describe the limits of a staged demo |

Relevant source files: [standing rules](https://github.com/anthropics/oncall-kit/blob/c03282cd5381a5a2e12e32bfb3c8957d52ce01f1/CLAUDE.md), [triage](https://github.com/anthropics/oncall-kit/blob/c03282cd5381a5a2e12e32bfb3c8957d52ce01f1/skills/triage/SKILL.md), [evaluation](https://github.com/anthropics/oncall-kit/blob/c03282cd5381a5a2e12e32bfb3c8957d52ce01f1/eval/replay.md).

## Deliberate differences

The kit is a broader, vendor-neutral operating workflow with Slack, capability discovery, policy review, incident-history mining and evaluation gates. Our demo is one local application for one Google Cloud shop. It automatically creates an investigation record from a Monitoring incident; that is not a claim that the kit delegates incident declaration to an agent.

We omit correlation, paging, weekly reports, historical playbook mining and parallel investigators. We also defer automatic rollback to keep the first version centred on diagnosis. The model has no infrastructure mutation tool. A manual script performs the fix.

## Video sequence

Start with the broken checkout and the first useful finding. Then explain the architecture in five parts: a real service, deterministic alerting, evidence tools, an agent loop and persistent incident context.

Use the Anthropic reference to establish the operating principles. Distinguish their reported experience from this controlled demonstration. Show our prompt and four tools briefly, then return to the incident: inspect the error, compare deployment time, challenge the hypothesis and perform the manual rollback. Finish by checking the original failure path and saving a human-written lesson.

The strongest claim this demo can support is that an agent can gather and explain evidence from connected systems. It does not establish general root-cause accuracy, autonomous production safety or a measured reduction in incident duration.

## Rehearsal evaluation

For each real run, save the triggering alert, the first diagnosis, query links, revision names, timestamps, human action and observed outcome. Grade independently: correct, partially correct, wrong or harmful. Check that evidence opens, the proposed fix targets the correct service/revision, and uncertainty is visible. A scripted happy path alone is not an evaluation set.

Do not put the resolution into the initial test prompt. Do not fabricate past incidents or report seeded history as learned experience. Until multiple real runs are graded, describe reliability as unverified.
