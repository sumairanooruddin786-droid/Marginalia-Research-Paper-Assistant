class AppError(Exception):
    """An error with a user-friendly message and an HTTP status code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
