# Security policy

System Neuron Flow AI is an early prototype kept by one person. It holds synthetic data only. The online
demo at https://neuron-flow.onrender.com answers `/v1` requests only with an access key that is not
published.

> ภาษาไทย: ถ้าพบช่องโหว่ อย่าเปิด issue สาธารณะ ให้แจ้งแบบส่วนตัวผ่านแท็บ Security → Report a vulnerability

## Reporting a vulnerability

Please do not open a public issue. Report it privately instead: open this repository's **Security** tab
and choose **Report a vulnerability**. The owner reads the reports. There is no bounty and no promised
response time.

A useful report says what you found, how to reproduce it, and what it could affect.

## Scope

- In scope: the code in this repository (`neuron_flow/`, `app/`), its GitHub Actions workflows and the
  Render Blueprint (`render.yaml`).
- Out of scope: the outside services it can call (Typhoon, Claude, Sentry, Honeycomb, Render). Report
  problems in those to their vendors.

## What is already in place

- Keys come only from the environment at call time, never from files, logs or Sentry events (ADR-013).
- The *Secret scan* workflow runs gitleaks over every commit of every branch on every push and pull request.
- Every workflow's token is read-only, and no workflow uses `pull_request_target`
  (`tests/test_workflow_permissions.py`).
- Personal data is masked before every AI call. The masking is pattern-based, so it lowers the risk but does
  not make real data safe (ROADMAP 7.1).

Known limits are listed under [Scope and limits](README.md#scope-and-limits) in the README.
