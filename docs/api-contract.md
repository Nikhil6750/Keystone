# Keystone API Contract

This document tracks the REST API surface as it is implemented. Only endpoints that
actually exist in `backend/app/` are listed here.

## Base URL

Local development: `http://localhost:8000`

## Endpoints

### `GET /`

Root endpoint confirming the service is running.

**Response `200 OK`**

```json
{
  "service": "keystone-backend",
  "version": "0.1.0"
}
```

### `GET /api/v1/health`

Health check endpoint.

**Response `200 OK`**

```json
{
  "status": "healthy",
  "service": "keystone-backend",
  "version": "0.1.0"
}
```

## Planned, not yet implemented

Workflow orchestration endpoints (create/inspect/cancel workflows, agent step results,
audit event retrieval) will be added here as they are implemented. They do not exist yet.

Workflow domain schemas (`WorkflowCreate`, `WorkflowStepCreate`, `WorkflowRead`,
`WorkflowStepRead`, `StepAttemptRead`) now exist internally at
`backend/app/schemas/workflow.py` and are used by the persistence service
(`backend/app/services/workflow_service.py`), but are not yet exposed through any API
route.
