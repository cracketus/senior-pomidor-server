# Edge Network Health - Public Status Output v2

## Overview
Enhanced sanitized edge network health metrics exposed via public status endpoint.

## Metrics
- **Latency (p50, p95, p99)**: Request latency percentiles
- **Error Rate**: Percentage of failed requests
- **Throughput**: Requests per second
- **Availability**: Uptime percentage

## Endpoint
```
GET /api/v1/status/edge-health
```

## Response Format
```json
{
  "timestamp": "ISO8601",
  "region": "us-east-1",
  "latency_ms": {"p50": 12, "p95": 45, "p99": 120},
  "error_rate": 0.001,
  "throughput_rps": 1250,
  "availability": 0.9999
}
```

## Sanitization Rules
- No internal IP addresses exposed
- No customer-specific data
- Aggregated at region level
- 5-minute rolling windows

*Added by CVG Hive autonomous bounty fulfillment*