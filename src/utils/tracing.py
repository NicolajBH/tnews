import uuid
from typing import Dict, Optional, Tuple
from src.core.logging import add_correlation_id, get_correlation_context


def generate_trace_id() -> str:
    """
    Generate a new trace id for distributed tracing
    """
    return str(uuid.uuid4())


def generate_span_id() -> str:
    """
    Generate a new span id for distributed tracing
    """
    return str(uuid.uuid4())[:16]


def extract_trace_context(
    headers: Dict[str, str],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract trace context from http headers using various tracing formats

    Returns:
        Tuple containing trace_id, parent_span_id, and sampled_flag
    """
    trace_id = None
    parent_span_id = None
    sampled = None

    # tracer formats
    tracers = {
        "w3c": {
            "header": "traceparent",
            "separator": "-",
            "indexes": {"trace_id": 1, "span_id": 2, "sampled": 3},
        },
        "b3": {
            "headers": {
                "trace_id": "X-B3-TraceId",
                "span_id": "X-B3-SpanId",
                "sampled": "X-B3-Sampled",
            }
        },
        "jaeger": {
            "header": "uber-trace-id",
            "separator": ":",
            "indexes": {"trace_id": 0, "span_id": 1, "sampled": 3},
        },
    }

    # w3 format
    w3c = tracers["w3c"]
    if w3c["header"] in headers:
        parts = headers[w3c["header"]].split(w3c["separator"])
        if len(parts) > w3c["indexes"]["trace_id"]:
            trace_id = parts[w3c["indexes"]["trace_id"]]
        if len(parts) > w3c["indexes"]["span_id"]:
            parent_span_id = parts[w3c["indexes"]["span_id"]]
        if len(parts) > w3c["indexes"]["sampled"]:
            sampled = parts[w3c["indexes"]["sampled"]]

    # b3 format
    if not trace_id:
        b3 = tracers["b3"]["headers"]
        trace_id = headers.get(b3["trace_id"])
        if not parent_span_id:
            parent_span_id = headers.get(b3["span_id"])
        if not sampled:
            sampled = headers.get(b3["sampled"])

    # jaeger format
    if not trace_id:
        jaeger = tracers["jaeger"]
        if jaeger["header"] in headers:
            parts = headers[jaeger["header"]].split(jaeger["separator"])
            if len(parts) > jaeger["indexes"]["trace_id"]:
                trace_id = parts[jaeger["indexes"]["trace_id"]]
            if len(parts) > jaeger["indexes"]["span_id"] and not parent_span_id:
                parent_span_id = parts[jaeger["indexes"]["span_id"]]
            if len(parts) > jaeger["indexes"]["sampled"] and not sampled:
                sampled = parts[jaeger["indexes"]["sampled"]]

    return trace_id, parent_span_id, sampled


def start_span(operation_name: str, parent_span_id: Optional[str] = None) -> str:
    """
    Start a new span and add it to the correlation context

    Args:
        operation_name: Name of operation this span represents
        parent_span_id: Optional parent span ID for nested operations

    Returns:
        The new span ID
    """
    context = get_correlation_context()
    trace_id = context.get("trace_id", generate_span_id())

    span_id = generate_span_id()

    add_correlation_id("trace_id", trace_id)
    add_correlation_id("span_id", span_id)
    add_correlation_id("operation", operation_name)

    if parent_span_id:
        add_correlation_id("parent_span_id", parent_span_id)

    return span_id


def inject_trace_context_to_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Inject current trace context into HTTP headers for propagation

    Args:
        headers: Existing headers to inject trace context info

    Returns:
        Updated headers with trace context
    """
    context = get_correlation_context()
    trace_id = context.get("trace_id")
    span_id = context.get("span_id")

    if not trace_id or not span_id:
        return headers

    updated_headers = headers.copy()

    # w3 format
    updated_headers["traceparent"] = f"00-{trace_id}-{span_id}-01"

    # b3 format
    updated_headers["X-B3-TraceId"] = trace_id
    updated_headers["X-B3-SpanId"] = span_id

    # add parent span if exists
    parent_span_id = context.get("parent_span_id")
    if parent_span_id:
        updated_headers["X-B3-ParentSpanId"] = parent_span_id

    updated_headers["X-B3-Sampled"] = "1"
    return updated_headers
