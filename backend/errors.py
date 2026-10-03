class BusinessConflict(ValueError):
    """A recoverable conflict; callers must reload before issuing another write."""
    def __init__(self, code, message, current_version=None):
        super().__init__(message)
        self.code = code
        self.current_version = current_version

    def detail(self):
        value = {"code": self.code, "message": str(self)}
        if self.current_version is not None:
            value["current_version"] = self.current_version
        return value
