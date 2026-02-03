# Claude Code Tracer

By [Silverstream AI](https://silverstream.ai)

A Claude Code hook that traces your sessions and sends them to [Bench](https://bench.silverstream.ai), an agent benchmarking and debugging platform.

Every tool call, prompt, and assistant response is captured as an OpenTelemetry span and streamed to your Bench endpoint in real time. Claude Code handles the rest of the setup automatically once your endpoint is configured — just follow the steps on [bench.silverstream.ai](https://bench.silverstream.ai).
