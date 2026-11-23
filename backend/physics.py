from .language import tr
import ast
import math
import operator
import re
from pint import UnitRegistry
from .models import Motion

units = UnitRegistry()
operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.Pow: operator.pow}
functions = {name: getattr(math, name) for name in ("sqrt", "sin", "cos", "tan", "log", "log10", "exp")}


def calculate(expression):
    if len(expression) > 240:
        raise ValueError(tr("Biểu thức quá dài.", "The expression is too long."))
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 80:
        raise ValueError(tr("Biểu thức quá phức tạp.", "The expression is too complex."))

    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = float(node.value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            result = value(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError(tr("Số mũ quá lớn.", "The exponent is too large."))
            result = operations[type(node.op)](left, right)
        elif isinstance(node, ast.Name) and node.id in ("pi", "e"):
            result = getattr(math, node.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions and len(node.args) == 1 and not node.keywords:
            result = functions[node.func.id](value(node.args[0]))
        else:
            raise ValueError(tr("Phép tính không được hỗ trợ.", "This operation is not supported."))
        if isinstance(result, complex) or not math.isfinite(result):
            raise ValueError(tr("Kết quả ngoài miền số thực hữu hạn.", "The result is outside the range of finite real numbers."))
        return result
    return value(tree.body)


def motion_point(config: Motion, t):
    return dict(t=t, s=config.velocity*t + config.acceleration*t*t/2,
                v=config.velocity + config.acceleration*t)


def motion(config: Motion):
    points = [motion_point(config, config.duration * i / 240) for i in range(241)]
    marks = [dict(t=t, s=config.velocity*t + config.acceleration*t*t/2)
             for t in range(math.floor(config.duration)+1)]
    return dict(params=config.model_dump(), points=points, marks=marks)


def parse_quantity(text):
    text = text.replace("·", "*").replace("⋅", "*")
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*([\wµ°/*^ .²³⁻-]{0,40})\s*", text)
    if not match:
        raise ValueError(tr("Hãy nhập một số và đơn vị phù hợp.", "Enter a number and an appropriate unit."))
    try:
        number = float(match[1].replace(",", "."))
        if not math.isfinite(number):
            raise ValueError()
        unit = match[2].strip()
        return units.Quantity(number, units.parse_units(unit or "dimensionless")), bool(unit)
    except Exception as exc:
        raise ValueError(tr("Số hoặc đơn vị không hợp lệ.", "Invalid number or unit.")) from exc


def quantity(text):
    return parse_quantity(text)[0]


def assess(question, answer):
    if question["kind"] == "choice":
        return question["answer"] == answer, None, None
    expected = quantity(question["answer"])
    actual, has_unit = parse_quantity(answer)
    powers = sorted(expected.dimensionality.items())
    dimension = " ".join(f"{name}^{power:g}" if power != 1 else name for name, power in powers) or "dimensionless"
    if not actual.is_compatible_with(expected):
        return False, "incompatible_unit" if has_unit else "missing_unit", dimension
    correct = math.isclose(actual.to(expected.units).magnitude, expected.magnitude, rel_tol=0.001, abs_tol=1e-9)
    return correct, "correct" if correct else None, dimension


def grade(question, answer):
    return assess(question, answer)[0]

