"""
ADOT TracerProvider setup.

Initializes OpenTelemetry with AwsXRayIdGenerator and exports spans via OTLP gRPC
to the endpoint configured by OTEL_EXPORTER_OTLP_ENDPOINT (default: http://localhost:4317).
"""
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator


def init_tracer() -> TracerProvider:
    """
    Initialize ADOT TracerProvider with AwsXRayIdGenerator and service.name resource.
    Exporter endpoint from OTEL_EXPORTER_OTLP_ENDPOINT env var.
    """
    resource = Resource.create({
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "ace-orchestrator"),
    })
    provider = TracerProvider(
        id_generator=AwsXRayIdGenerator(),
        resource=resource,
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider
