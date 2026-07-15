"""Research Chat: the admin's personal sparring/research chat (design doc 11).

Deliberately a sibling of `app/research/`, not a child: the Research Agent owns
the report format's auditable 6-phase harness, while this owns a short-lived
per-message graph. Chat reuses research's connectors, fetcher, rubric, Budget and
`llm.structured` seam, but shares none of its state model — chat's durable state
is Firestore `chatThreads/`, not `researchRuns/`.
"""
