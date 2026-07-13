class ParserError(Exception):
    pass


class ParserUnsupportedFormatError(ParserError):
    pass


class ParserDecodeError(ParserError):
    pass


class ParserLimitError(ParserError):
    pass


class ParserExecutionError(ParserError):
    pass
