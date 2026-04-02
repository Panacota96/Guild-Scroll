# Case Studies

Short notes on architecture decisions observed in production LLM systems.

## Karpathy HN Time Capsule

- Strong fit for batch pipelines.
- Structured output requirements improve parse reliability.
- Staged file-based processing supports repeatability.

## Vercel d0 Tool Reduction

- Reduced tool surface area improved reliability.
- Primitive interfaces sometimes outperform specialized wrappers.
- Tool ambiguity is a frequent source of failure.

## Multi-Agent Research Workflows

- Context isolation can outperform single-agent long-context chains.
- Shared file artifacts preserve fidelity better than repeated summarization.
- Evaluation checkpoints are required to avoid drift.
