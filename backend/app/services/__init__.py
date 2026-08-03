"""Application services coordinating engine, adapters, and persistence.

`workflow_service.py` implements workflow/step/attempt persistence, including
recording aggregated execution results (`set_workflow_result`). Compensation
services are not yet implemented.
"""
