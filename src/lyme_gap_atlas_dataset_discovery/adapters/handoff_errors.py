"""Conservative structured connector classification without inspecting error text."""

from snowflake.connector.errorcode import ER_CONNECTION_IS_CLOSED, ER_CONNECTION_TIMEOUT
from snowflake.connector.errors import Error

from lyme_gap_atlas_dataset_discovery.domain.handoff import (
    HandoffFailureKind,
    HandoffOperationError,
)


def classify_handoff_error(error: Error | TimeoutError | ConnectionError) -> HandoffOperationError:
    retryable = isinstance(error, (TimeoutError, ConnectionError)) or (
        isinstance(error, Error)
        and (
            error.errno in {ER_CONNECTION_IS_CLOSED, ER_CONNECTION_TIMEOUT}
            or error.sqlstate in {"08006", "08007", "40001"}
        )
    )
    return HandoffOperationError(
        HandoffFailureKind.RETRYABLE_FAILURE if retryable else HandoffFailureKind.TERMINAL_FAILURE
    )
