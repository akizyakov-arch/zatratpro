"""Provider-independent recognition failures; messages never include credentials."""
class RecognitionError(RuntimeError):
    def __init__(self, message, *, code=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
