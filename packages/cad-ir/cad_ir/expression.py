import math
import re
from collections.abc import Mapping


class ExpressionError(ValueError):
    pass


_TOKEN = re.compile(
    r"\s*(?:(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<name>[A-Za-z][A-Za-z0-9_.-]{0,63})|(?P<operator>[()+\-*/,]))"
)


def evaluate_expression(expression: str, parameters: Mapping[str, float]) -> float:
    if not expression or len(expression) > 512:
        raise ExpressionError("expression length is outside the allowed range")
    parser = _Parser(expression, parameters)
    value = parser.parse()
    if not math.isfinite(value) or abs(value) > 1_000_000:
        raise ExpressionError("expression result is not a finite bounded number")
    return value


def referenced_parameters(expression: str) -> set[str]:
    tokens = _tokenize(expression)
    return {
        value
        for index, (kind, value) in enumerate(tokens)
        if kind == "name"
        and value != "pi"
        and not (index + 1 < len(tokens) and tokens[index + 1][1] == "(")
    }


def _tokenize(source: str) -> list[tuple[str, str]]:
    if not source or len(source) > 512:
        raise ExpressionError("expression length is outside the allowed range")
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(source):
        match = _TOKEN.match(source, position)
        if match is None:
            raise ExpressionError(f"invalid token at character {position}")
        kind = match.lastgroup
        assert kind is not None
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, source: str, parameters: Mapping[str, float]):
        self.parameters = parameters
        self.tokens = _tokenize(source)
        self.index = 0

    def parse(self) -> float:
        result = self._sum()
        if self.index != len(self.tokens):
            raise ExpressionError("unexpected token")
        return result

    def _sum(self) -> float:
        value = self._product()
        while self._peek("+", "-"):
            operator = self._take()[1]
            right = self._product()
            value = value + right if operator == "+" else value - right
        return value

    def _product(self) -> float:
        value = self._unary()
        while self._peek("*", "/"):
            operator = self._take()[1]
            right = self._unary()
            if operator == "/" and right == 0:
                raise ExpressionError("division by zero")
            value = value * right if operator == "*" else value / right
        return value

    def _unary(self) -> float:
        if self._peek("+", "-"):
            operator = self._take()[1]
            value = self._unary()
            return value if operator == "+" else -value
        return self._primary()

    def _primary(self) -> float:
        token = self._take()
        if token[0] == "number":
            return float(token[1])
        if token[1] == "(":
            value = self._sum()
            self._expect(")")
            return value
        if token[0] != "name":
            raise ExpressionError("number, parameter or function expected")
        name = token[1]
        if self._peek("("):
            return self._function(name)
        if name == "pi":
            return math.pi
        try:
            return float(self.parameters[name])
        except KeyError as error:
            raise ExpressionError(f"unknown parameter: {name}") from error

    def _function(self, name: str) -> float:
        if name not in {"min", "max", "abs"}:
            raise ExpressionError(f"function is not allowed: {name}")
        self._expect("(")
        arguments = [self._sum()]
        while self._peek(","):
            self._take()
            arguments.append(self._sum())
        self._expect(")")
        if name == "abs":
            if len(arguments) != 1:
                raise ExpressionError("abs expects one argument")
            return abs(arguments[0])
        if len(arguments) < 2:
            raise ExpressionError(f"{name} expects at least two arguments")
        return min(arguments) if name == "min" else max(arguments)

    def _peek(self, *values: str) -> bool:
        return self.index < len(self.tokens) and self.tokens[self.index][1] in values

    def _take(self) -> tuple[str, str]:
        if self.index >= len(self.tokens):
            raise ExpressionError("unexpected end of expression")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _expect(self, value: str) -> None:
        if not self._peek(value):
            raise ExpressionError(f"expected '{value}'")
        self._take()
