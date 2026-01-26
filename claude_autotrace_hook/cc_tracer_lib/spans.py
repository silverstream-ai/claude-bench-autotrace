from typing import Any
from uuid import UUID

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    SpanKind,
    Status,
    StatusCode,
    TraceFlags,
    Tracer,
    set_span_in_context,
)

from cc_tracer_lib.models import (
    AL2_HARNESS,
    AL2_MODEL,
    INSTRUMENTATION_NAME,
    INSTRUMENTATION_VERSION,
    SERVICE_NAME,
    TRACE_ENDPOINT_PATH,
)


def uuid_to_int(uuid: UUID, bits: int) -> int:
    hex_str = str(uuid).replace("-", "")
    if bits == 64:
        hex_str = hex_str[:16]
    return int(hex_str, 16)


def make_context(trace_id: UUID, parent_span_id: UUID | None = None) -> Context:
    span_context = SpanContext(
        trace_id=uuid_to_int(trace_id, 128),
        span_id=uuid_to_int(parent_span_id, 64) if parent_span_id is not None else 0,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(span_context))


def setup_tracer(
    collector_base_url: str, endpoint_code: str, model: str, harness: str
) -> Tracer:
    endpoint = collector_base_url + TRACE_ENDPOINT_PATH.format(endpoint_code)
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            AL2_MODEL: model,
            AL2_HARNESS: harness,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=2))
    )
    trace.set_tracer_provider(provider)
    return trace.get_tracer(INSTRUMENTATION_NAME, INSTRUMENTATION_VERSION)


def _is_otel_serializable(value: Any) -> bool:
    """
    OTel only supports some data types
    """
    supported_otel_types = str | int | float | bool
    if isinstance(value, supported_otel_types):
        return True
    return isinstance(value, list) and all(
        isinstance(x, supported_otel_types) for x in value
    )


def send_span(
    tracer: Tracer,
    name: str,
    attributes: dict[str, Any],
    start_time_ns: int,
    end_time_ns: int,
    context: Context,
    trace_id: UUID,
    explicit_span_id: UUID | None = None,
) -> None:
    span = tracer.start_span(
        name, kind=SpanKind.INTERNAL, start_time=start_time_ns, context=context
    )
    for key, value in attributes.items():
        span.set_attribute(key, value if _is_otel_serializable(value) else str(value))
    span.set_status(Status(StatusCode.OK))

    # WTF is this?
    span._context = SpanContext(  # type: ignore[attr-defined]
        trace_id=uuid_to_int(trace_id, 128),
        span_id=uuid_to_int(explicit_span_id, 64)
        if explicit_span_id is not None
        else span.context.span_id,  # type: ignore[attr-defined]
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )

    span.end(end_time=end_time_ns)
