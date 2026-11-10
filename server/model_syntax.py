"""Logical lines, block structure, and calculation expansion for model text."""

from __future__ import annotations

import ast
import math
import re
from collections import ChainMap
from collections.abc import Mapping
from dataclasses import dataclass

from transforms import _degree_quaternion


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\Z")
EXPRESSION_CONSTANTS = {"pi": math.pi, "e": math.e}
EXPRESSION_FUNCTIONS = {
    "sin": (math.sin, 1), "cos": (math.cos, 1), "tan": (math.tan, 1),
    "asin": (math.asin, 1), "acos": (math.acos, 1), "atan": (math.atan, 1),
    "atan2": (math.atan2, 2), "exp": (math.exp, 1), "log": (math.log, 1),
    "sqrt": (math.sqrt, 1), "abs": (abs, 1),
    "radians": (math.radians, 1), "degrees": (math.degrees, 1),
}


class ExpressionScope(ChainMap):
    """Numeric bindings and calculation functions travel together through CAD scopes."""

    def __init__(self, inherited=(), *, values=None, functions=None):
        if isinstance(inherited, ExpressionScope):
            super().__init__(inherited.maps[0].copy(), *inherited.maps[1:])
            self.functions = ChainMap(inherited.functions.maps[0].copy(), *inherited.functions.maps[1:])
        else:
            super().__init__(dict(inherited), {} if values is None else values)
            self.functions = ChainMap({}, {} if functions is None else functions)


DECIMAL = r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
DECIMAL_LITERAL = re.compile(r"[+-]?" + DECIMAL)
_EXPRESSION_TOKEN = re.compile(DECIMAL + r"""|[A-Za-z_][A-Za-z_0-9]*|'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|\S""")


def _decimal_expression(source):
    tokens = _EXPRESSION_TOKEN.findall(source)
    if len(tokens) > 512:
        raise ValueError("expression must contain at most 512 tokens")
    if tokens[-1:] == [","] or any(a == "," and b == ")" for a, b in zip(tokens, tokens[1:])):
        raise ValueError("trailing comma in expression")
    depth = 0
    for i, token in enumerate(tokens):
        if token == "(":
            depth += 1
            if depth > 32:
                raise ValueError("expression is too deeply nested")
        elif token == ")":
            depth -= 1
        elif token in ("NaN", "Infinity"):
            raise ValueError("number must be finite")
        elif token.isascii() and token.isdecimal():
            tokens[i] = token.lstrip("0") or "0"
        elif not (token in "+-*/,.=" or IDENTIFIER.fullmatch(token) or DECIMAL_LITERAL.fullmatch(token)
                  or len(token) >= 2 and token[0] in "'\"" and token[-1] == token[0]):
            raise ValueError("only numeric expressions and approved math functions are allowed")
    return " ".join(tokens)


def expression_tree(source):
    try:
        return ast.parse(_decimal_expression(source), mode="eval").body
    except (SyntaxError, RecursionError) as exc:
        raise ValueError(f"invalid expression: {source}") from exc


def number_expression(source, variables):
    """Evaluate the small numeric expression language without Python eval."""
    budget = [10000]

    def visit(node, bindings, depth=0):
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("expression evaluation limit exceeded (10000)")
        if depth > 32:
            raise ValueError("expression is too deeply nested")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.Name):
            if node.id in bindings:
                value = bindings[node.id]
            elif node.id in EXPRESSION_CONSTANTS:
                value = EXPRESSION_CONSTANTS[node.id]
            else:
                raise ValueError(f"unknown variable: {node.id}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            functions = getattr(bindings, "functions", {})
            if name not in EXPRESSION_FUNCTIONS and name not in functions:
                raise ValueError(f"unknown function: {name}")
            arity = (len(functions[name][0]) if name in functions
                     else EXPRESSION_FUNCTIONS[name][1])
            if node.keywords or len(node.args) != arity:
                raise ValueError(f"{name}: expected {arity} positional argument(s)")
            arguments = [visit(argument, bindings, depth + 1) for argument in node.args]
            if name in functions:
                parameters, body, captured, line = functions[name]
                local = ExpressionScope(captured)
                local.update(zip(parameters, arguments))
                try:
                    return visit(body, local, depth + 1)
                except ValueError as exc:
                    raise ValueError(f"{name} (defined at Line {line}): {exc}") from exc
            function = EXPRESSION_FUNCTIONS[name][0]
            try:
                value = function(*arguments)
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                raise ValueError(f"{name}: invalid argument or result: {exc}") from exc
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, bindings, depth + 1)
            if isinstance(node.op, ast.USub):
                value = -value
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left, bindings, depth + 1), visit(node.right, bindings, depth + 1)
            try:
                value = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                         ast.Mult: lambda: left * right, ast.Div: lambda: left / right}[type(node.op)]()
            except (ZeroDivisionError, OverflowError) as exc:
                raise ValueError(f"invalid arithmetic: {exc}") from exc
        else:
            raise ValueError("only numeric expressions and approved math functions are allowed")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("expression result must be finite")
        return value

    return visit(expression_tree(source), variables)


def _validate_tree(body, scope, *, parameters=(), max_nodes=10000, unknown_call_hint=""):
    remaining = max_nodes
    functions = getattr(scope, "functions", {})

    def visit(node, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise ValueError("expression validation limit exceeded")
        if depth > 32:
            raise ValueError("expression is too deeply nested")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            try:
                finite = math.isfinite(node.value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("expression result must be finite")
        elif isinstance(node, ast.Name):
            if node.id not in parameters and node.id not in scope and node.id not in EXPRESSION_CONSTANTS:
                raise ValueError(f"unknown variable: {node.id}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called = node.func.id
            if called not in functions and called not in EXPRESSION_FUNCTIONS:
                raise ValueError(f"unknown function: {called}{unknown_call_hint}")
            arity = (len(functions[called][0]) if called in functions
                     else EXPRESSION_FUNCTIONS[called][1])
            if node.keywords or len(node.args) != arity:
                raise ValueError(f"{called}: expected {arity} positional argument(s)")
            for argument in node.args:
                visit(argument, depth + 1)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            visit(node.operand, depth + 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            visit(node.left, depth + 1)
            visit(node.right, depth + 1)
        else:
            raise ValueError("only numeric expressions and approved math functions are allowed")
    visit(body)


def validate_number_expression(source, scope, *, max_nodes=10000):
    """Validate names and syntax without evaluating parameter-dependent arithmetic."""
    _validate_tree(expression_tree(source), scope, max_nodes=max_nodes)


def quaternion_expression(source, variables):
    """Read dquaternion(axis x, y, z, degrees) with bounded numeric arguments."""
    call = expression_tree(source)
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "dquaternion" and not call.keywords and len(call.args) == 4):
        raise ValueError("dquaternion: expected four positional arguments x, y, z, degrees")
    return _degree_quaternion(*[number_expression(ast.unparse(arg), variables) for arg in call.args])


def _fn_header(line):
    match = re.fullmatch(r"(?i:fn)\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(([^()]*)\)\s*=\s*(.+)", line)
    if not match:
        raise ValueError("fn: expected name(parameters) = expression")
    return match.groups()


def let_header(tail):
    match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.+)", tail)
    if not match:
        raise ValueError("let: expected name = expression")
    return match.groups()


def _define_calculation(line, scope, line_number):
    name, arguments, source = _fn_header(line)
    parameters = [item.strip() for item in arguments.split(",")] if arguments.strip() else []
    if any(not IDENTIFIER.fullmatch(item) for item in parameters):
        raise ValueError("fn: parameters must be identifiers")
    if len(parameters) != len(set(parameters)):
        raise ValueError("fn: duplicate parameter")
    if name in EXPRESSION_FUNCTIONS or name in EXPRESSION_CONSTANTS:
        raise ValueError(f"fn: reserved name: {name}")
    body = expression_tree(source)
    # Validate even unused definitions, without evaluating parameter-dependent domains.
    _validate_tree(body, scope, parameters=parameters,
                   unknown_call_hint=" (forward and recursive calls are unsupported)")
    return name, (parameters, body, ExpressionScope(scope), line_number)


def range_expressions(source):
    """Split range arguments at AST call boundaries, preserving nested call commas."""
    call = expression_tree(f"range({source})")
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "range" or call.keywords:
        raise ValueError("range arguments must be one to three integers")
    if not 1 <= len(call.args) <= 3:
        raise ValueError("range arguments must be one to three integers")
    return [ast.unparse(argument) for argument in call.args]


_RAW_PROPERTY_PREFIX = re.compile(r"\s*property\s+\S+\s+`", re.I)


def _split_comment(line):
    """Split at a comment marker outside a quoted string."""
    raw_property = _RAW_PROPERTY_PREFIX.match(line)
    raw_start = raw_property.end() - 1 if raw_property else -1
    quote, escaped = None, False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quote in ('"', "'") and char == "\\":
            escaped = True
        elif char == quote:
            quote = None
        elif not quote and (char in ('"', "'") or index == raw_start):
            quote = char
        elif not quote and char == "#":
            return line[:index], line[index:]
    return line, ""


_INTERPOLATION = re.compile(r"\$\{([^{}]+)\}")
_BLOCK_OPENERS = {"part", "group", "profile", "for", "if"}
_LOCAL_SCOPES = {"group", "profile"}
_FOR_HEADER = r"for\s+([A-Za-z_][A-Za-z_0-9]*)\s+in\s+range\((.*)\)"
_FOR_SYNTAX = "expected name in range(count) or range(start, stop[, step])"


def loop_header(text, *, ignore_case=False):
    """Read the variable name and range argument text shared by both languages."""
    match = re.fullmatch(_FOR_HEADER, text, re.I | re.ASCII if ignore_case else 0)
    if not match:
        raise ValueError(_FOR_SYNTAX)
    return match.groups()


def bounded_range(expressions, scope, limit):
    values = [number_expression(expression, scope) for expression in expressions]
    if any(not float(value).is_integer() for value in values):
        raise ValueError("range arguments must be one to three integers")
    if len(values) == 3 and values[2] == 0:
        raise ValueError("range step must not be zero")
    iteration = range(*map(int, values))
    try:
        count = len(iteration)
    except OverflowError:
        count = limit + 1
    if count > limit:
        raise ValueError(f"loop iteration limit exceeded ({limit})")
    return iteration


@dataclass(frozen=True, slots=True)
class Command:
    line: int
    text: str
    op: str
    tail: str

    @classmethod
    def read(cls, line, text):
        words = text.strip().split(None, 1)
        return cls(line, text, words[0].lower() if words else "", words[1] if len(words) == 2 else "")

    def error(self, message):
        return ValueError(f"Line {self.line}: {message}")


def command_records(source, *, line_error=Command.error):
    """Join continued physical lines; retain the start line and strip comments once."""
    fragments = []
    for line, raw in enumerate(source.splitlines(), 1):
        if not fragments:
            start = line
        stripped = raw.rstrip()
        if stripped.endswith("\\") and (
            "#" not in stripped or not _split_comment(" ".join([*fragments, stripped]))[1]
        ):
            fragments.append(stripped[:-1].rstrip())
            continue
        code = _split_comment(" ".join([*fragments, raw]))[0]
        yield Command.read(start, code.strip())
        fragments.clear()
    if fragments:
        raise line_error(Command.read(start, ""), "trailing backslash requires a following line")


def expression_arguments(text):
    """Split command fields, keeping grouped expressions together."""
    words, stack = [], []
    start = None
    for i, char in enumerate(text):
        if char.isspace() and not stack:
            if start is not None:
                words.append(text[start:i])
                start = None
            continue
        if start is None:
            start = i
        if char in "({":
            stack.append(char)
        elif char in ")}" and (not stack or stack.pop() != {")": "(", "}": "{"}[char]):
            raise ValueError("unmatched expression delimiter")
    if stack:
        raise ValueError("unmatched expression delimiter")
    if start is not None:
        words.append(text[start:])
    return words


def argument_expression(word):
    return word[2:-1] if word.startswith("${") and word.endswith("}") else word


def number_argument(word, scope):
    if word.lower().lstrip("+-") in {"nan", "inf", "infinity"} and word not in scope:
        raise ValueError("number must be finite")
    if DECIMAL_LITERAL.fullmatch(word):
        value = float(word)
    else:
        value = float(number_expression(argument_expression(word), scope))
    if not math.isfinite(value):
        raise ValueError("number must be finite")
    return value


def interpolate(code, scope, *, quaternion=False):
    def replace(match):
        expression = match[1].strip()
        if re.match(r"dquaternion\s*\(", expression):
            if not quaternion:
                raise ValueError("dquaternion is only allowed in a quaternion command")
            return " ".join(format(v, ".17g") for v in quaternion_expression(expression, scope))
        value = number_expression(expression, scope)
        return str(int(value)) if isinstance(value, int) or value.is_integer() else repr(value)

    result = _INTERPOLATION.sub(replace, code)
    if "${" in result:
        raise ValueError("unclosed or nested ${expression}")
    return result


def validate_interpolation(code, scope):
    def replace(match):
        validate_number_expression(match[1].strip(), scope)
        return "0"

    result = _INTERPOLATION.sub(replace, code)
    if "${" in result:
        raise ValueError("unclosed or nested ${expression}")
    return result


def _expand_text(command, scope):
    code = command.text
    raw_property = _RAW_PROPERTY_PREFIX.match(code)
    raw_start = raw_property.end() - 1 if raw_property else len(code)
    result = interpolate(code[:raw_start], scope, quaternion=command.op == "quaternion")
    return Command.read(command.line, result + code[raw_start:])


@dataclass
class ExpansionBudget:
    lines: int = 0
    visits: int = 0

    def visit(self, command):
        self.visits += 1
        if self.visits > 100_000:
            raise command.error("expansion work limit exceeded (100000)")

    def emit(self, command, count=1):
        self.lines += count
        if self.lines > 20_000:
            raise command.error("expanded line limit exceeded (20000)")


class ModelProgram:
    """Match end blocks once; expand the root or a part in its caller's scope."""

    def __init__(self, source):
        self.commands = list(command_records(source))
        self.ends = {}
        self.parts = {}
        stack = []
        for index, command in enumerate(self.commands):
            op, name = command.op, command.tail
            if op == "part":
                if stack:
                    message = ("part definitions cannot be nested" if self.commands[stack[0]].op == "part"
                               else "part definitions must be at the root level")
                    raise command.error(message)
                if not IDENTIFIER.fullmatch(name):
                    raise command.error("part: one valid part name required")
                if name in self.parts:
                    raise command.error(f"duplicate part name: {name}")
            if op in _BLOCK_OPENERS:
                stack.append(index)
            elif op == "end":
                if command.tail:
                    raise command.error("end takes no arguments")
                if not stack:
                    raise command.error("end requires an open block")
                start = stack.pop()
                self.ends[start] = index
                opener = self.commands[start]
                if opener.op == "part":
                    self.parts[opener.tail] = (start + 1, index)
        if stack:
            command = self.commands[stack[-1]]
            label = command.text if command.op in {"part", "group", "profile"} else command.op
            raise command.error(f"{label} has no end")

    def expand(self, budget, *, part=None, inherited=()):
        start, stop = self.parts[part] if part is not None else (0, len(self.commands))
        return list(self._expand(start, stop, inherited, budget))

    def root_calculations(self):
        index = 0
        while index < len(self.commands):
            command = self.commands[index]
            if command.op in {"let", "fn"}:
                yield command
            index = self.ends.get(index, index) + 1

    def _expand(self, start, stop, inherited, budget, depth=0):
        if depth > 32:
            raise ValueError("control block nesting limit exceeded (32)")
        scopes = [ExpressionScope(inherited)]
        snapshots = [None]
        definitions = [set()]
        index = start
        while index < stop:
            command = self.commands[index]
            op, scope = command.op, scopes[-1]
            budget.visit(command)
            try:
                if op == "fn":
                    name, function = _define_calculation(command.text, scope, command.line)
                    if name in definitions[-1]:
                        raise ValueError(f"duplicate function or variable: {name}")
                    scope.functions[name] = function
                    definitions[-1].add(name)
                    snapshots[-1] = None
                elif op == "let":
                    name, expression = let_header(command.tail)
                    if name in definitions[-1]:
                        raise ValueError(f"duplicate variable: {name}")
                    scope[name] = number_expression(expression, scope)
                    definitions[-1].add(name)
                    snapshots[-1] = None
                elif op == "for":
                    try:
                        name, arguments = loop_header(command.text, ignore_case=True)
                    except ValueError as exc:
                        raise ValueError(f"for: {exc}") from exc
                    if name in scope:
                        raise ValueError(f"loop variable already defined: {name}")
                    end = self.ends[index]
                    for value in bounded_range(range_expressions(arguments), scope, 512):
                        budget.visit(command)
                        nested = ExpressionScope(scope)
                        nested[name] = value
                        try:
                            yield from self._expand(index + 1, end, nested, budget, depth + 1)
                        except ValueError as exc:
                            raise ValueError(f"for {name}={value}: {exc}") from exc
                    index = end
                elif op == "if":
                    if not command.tail:
                        raise ValueError("if: expected a numeric expression")
                    end = self.ends[index]
                    if number_expression(command.tail, scope) != 0:
                        yield from self._expand(index + 1, end, scope, budget, depth + 1)
                    index = end
                elif op == "part":
                    end = self.ends[index]
                    budget.emit(command, end - index + 1)
                    index = end
                else:
                    budget.emit(command)
                    if op:
                        expanded = _expand_text(command, scope)
                        if snapshots[-1] is None:
                            snapshots[-1] = ExpressionScope(scope)
                        yield expanded, snapshots[-1]
                    if op in _LOCAL_SCOPES:
                        scopes.append(ExpressionScope(scope))
                        snapshots.append(None)
                        definitions.append(set())
                    elif op == "end":
                        scopes.pop()
                        snapshots.pop()
                        definitions.pop()
            except ValueError as exc:
                if str(exc).startswith("Line "):
                    raise
                raise command.error(str(exc)) from exc
            index += 1


@dataclass(frozen=True)
class _Declaration:
    command: Command
    name: str
    section: int
    index: int
    expression: str

    def error(self, message):
        if self.section:
            return ValueError(f"Animation line {self.command.line}: {message}")
        return self.command.error(message)


class _VisibleBindings(Mapping):
    """A lexical view; a cross-section reference resolves its declaration on demand."""

    def __init__(self, owner, definitions, before):
        self.owner, self.definitions, self.before = owner, definitions, before

    def __contains__(self, name):
        definition = self.definitions.get(name)
        return definition is not None and definition.index < self.before[definition.section]

    def __getitem__(self, name):
        if name not in self:
            raise KeyError(name)
        return self.owner.resolve(self.definitions[name])

    def __iter__(self):
        return (name for name in self.definitions if name in self)

    def __len__(self):
        return sum(1 for _ in self)


class SharedCalculations:
    """One namespace for the two sources, preserving lexical order within each."""

    def __init__(self, model=(), animation=(), inherited=()):
        self.values, self.functions = {}, {}
        self.inherited = ExpressionScope(inherited)
        self.cache, self.active = {}, []
        self.counts = [0, 0]
        for section, commands in enumerate((model, animation)):
            for index, command in enumerate(commands):
                try:
                    if command.op == "let":
                        name, expression = let_header(command.tail)
                        definitions = self.values
                    else:
                        name, _, expression = _fn_header(command.text)
                        definitions = self.functions
                except ValueError as exc:
                    prefix = "Animation line" if section else "Line"
                    raise ValueError(f"{prefix} {command.line}: {exc}") from exc
                declaration = _Declaration(command, name, section, index, expression)
                if name in self.values or name in self.functions or name in self.inherited or name in self.inherited.functions:
                    kind = "duplicate variable" if command.op == "let" and name not in self.functions else "duplicate function or variable"
                    raise declaration.error(f"{kind}: {name}")
                definitions[name] = declaration
                self.counts[section] = index + 1

    def scope(self, before=None):
        bounds = self.counts.copy()
        if before is not None:
            bounds[before.section] = before.index
        scope = ExpressionScope(values=_VisibleBindings(self, self.values, bounds),
                                functions=_VisibleBindings(self, self.functions, bounds))
        scope.update(self.inherited)
        scope.functions.update(self.inherited.functions)
        return scope

    def resolve(self, declaration):
        name = declaration.name
        if name in self.cache:
            return self.cache[name]
        if name in self.active:
            raise declaration.error(f"cyclic global definition: {' -> '.join([*self.active, name])}")
        if len(self.active) >= 64:
            raise declaration.error("global definition dependency limit exceeded (64)")
        self.active.append(name)
        try:
            scope = self.scope(declaration)
            if declaration.command.op == "let":
                value = number_expression(declaration.expression, scope)
            else:
                _, value = _define_calculation(declaration.command.text, scope, declaration.command.line)
            self.cache[name] = value
            return value
        except ValueError as exc:
            if str(exc).startswith(("Line ", "Animation line ")):
                raise
            raise declaration.error(str(exc)) from exc
        finally:
            self.active.pop()

    def animation_values(self):
        return {name: self.resolve(declaration) for name, declaration in self.values.items()
                if declaration.section == 1}

    def resolved_scope(self):
        declarations = sorted([*self.values.values(), *self.functions.values()],
                              key=lambda item: (item.section, item.index))
        for declaration in declarations:
            self.resolve(declaration)
        return self.scope()
