# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Owain, operating a Google Cloud demo and recording a video about AI incident investigation.

## Product Purpose

A local console where a human starts or receives an incident investigation, reads the agent's findings and supporting evidence, and asks follow-up questions.

## Operating Context

The demo shop runs on Cloud Run. Monitoring alerts reach a local worker through Pub/Sub. A Claude Agent SDK backend investigates real Google Cloud telemetry; PostgreSQL stores the incident record.

## Capabilities and Constraints

The v1 emphasizes investigation, conversation, evidence and human incident closure. Missing telemetry must remain explicitly unknown. The frontend must not fabricate health, metrics, incidents or tool activity. Browser requests use the local API and its CSRF token.

## Brand Commitments

A minimal, restrained, dark operations console suitable for a screen recording. Simple language and legible information take priority.

## Product Principles

- Show findings alongside their evidence.
- Distinguish an active incident from an active agent run.
- Keep a human in control of incident closure.
- Preserve the operator's question when a request fails.

## Open Decisions

React and Vite are the implementation team's default for this surface. Investigation-first layout is an inferred default pending the parent's optional user question.
