"""Incremental view of a streamed assistant response for live progress.

The model streams one JSON object. ``ReplyScanner`` follows only its top-level
``reply`` string so creators can read the reply as it is written, and counts the
objects opened directly inside ``proposal.operations`` for the drafting step. It
is a preview only: the complete response is still parsed and validated strictly.
"""

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_OPERATIONS = ("proposal", "operations")


class _Frame:
    __slots__ = ("array", "expects_key", "key")

    def __init__(self, array: bool) -> None:
        self.array = array
        self.key: str | None = None
        self.expects_key = not array


class ReplyScanner:
    def __init__(self) -> None:
        self._stack: list[_Frame] = []
        self._string: str | None = None  # "key", "value" or "reply" while inside a string
        self._key: list[str] = []
        self._escape = False
        self._hex: str | None = None
        self._high: int | None = None
        self._done = False
        self.operations = 0
        self.proposal_started = False

    def feed(self, chunk: str) -> str:
        """Consume the next characters; return newly decoded reply text."""
        out: list[str] = []
        for char in chunk:
            if self._done:
                break
            if self._string is not None:
                self._string_char(char, out)
            elif not self._stack:
                if char == "{":
                    self._stack.append(_Frame(array=False))
            else:
                self._structure(char)
        return "".join(out)

    def _structure(self, char: str) -> None:
        frame = self._stack[-1]
        if char == '"':
            if frame.expects_key:
                self._string, self._key = "key", []
            else:
                top_reply = len(self._stack) == 1 and frame.key == "reply"
                self._string = "reply" if top_reply else "value"
        elif char == ":" and not frame.array:
            frame.expects_key = False
        elif char == "," and not frame.array:
            frame.key, frame.expects_key = None, True
        elif char in "{[":
            if char == "{" and len(self._stack) == 1 and frame.key == "proposal":
                self.proposal_started = True
            if char == "{" and self._in_operations():
                self.operations += 1
            self._stack.append(_Frame(array=char == "["))
        elif char in "}]":
            self._stack.pop()
            if not self._stack:
                self._done = True

    def _in_operations(self) -> bool:
        stack = self._stack
        return (
            len(stack) == 3
            and not stack[0].array
            and not stack[1].array
            and stack[2].array
            and (stack[0].key, stack[1].key) == _OPERATIONS
        )

    def _string_char(self, char: str, out: list[str]) -> None:
        if self._hex is not None:
            self._hex += char
            if len(self._hex) == 4:
                code, self._hex = self._hex, None
                try:
                    self._emit_code(int(code, 16), out)
                except ValueError:
                    self._emit("�", out)
            return
        if self._escape:
            self._escape = False
            if char == "u":
                self._hex = ""
            else:
                self._emit(_ESCAPES.get(char, char), out)
            return
        if char == "\\":
            self._escape = True
        elif char == '"':
            self._flush_high(out)
            if self._string == "key":
                self._stack[-1].key = "".join(self._key)
            self._string = None
        else:
            self._emit(char, out)

    def _emit_code(self, code: int, out: list[str]) -> None:
        if 0xD800 <= code <= 0xDBFF:
            self._flush_high(out)
            self._high = code
        elif 0xDC00 <= code <= 0xDFFF:
            if self._high is None:
                self._emit("�", out)
            else:
                pair = 0x10000 + ((self._high - 0xD800) << 10) + (code - 0xDC00)
                self._high = None
                self._emit(chr(pair), out)
        else:
            self._emit(chr(code), out)

    def _flush_high(self, out: list[str]) -> None:
        if self._high is not None:
            self._high = None
            self._append("�", out)

    def _emit(self, text: str, out: list[str]) -> None:
        self._flush_high(out)
        self._append(text, out)

    def _append(self, text: str, out: list[str]) -> None:
        if self._string == "reply":
            out.append(text)
        elif self._string == "key":
            self._key.append(text)
