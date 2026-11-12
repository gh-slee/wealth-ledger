"""Independently evaluate the bounded OpenFormula subset used in report workbooks."""
from decimal import Decimal, localcontext
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
      "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}
TOKEN = re.compile(r'\s*(\[[^\]]+\]|"(?:[^"]|"")*"|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|[A-Za-z_]+|<=|>=|<>|[-+*/&=<>();])')
ADDRESS = re.compile(r"(?:'((?:[^']|'')+)'|([^'.]+))?\.\$?([A-Z]+)\$?(\d+)$")


def _parse(formula):
    source = formula.removeprefix("of:=")
    tokens, end = [], 0
    while end < len(source):
        match = TOKEN.match(source, end)
        if not match:
            raise ValueError(f"Unsupported OpenFormula syntax near {source[end:end+25]}")
        tokens.append(match.group(1))
        end = match.end()
    index = 0

    def take():
        nonlocal index
        value = tokens[index]
        index += 1
        return value

    def primary():
        token = take()
        if token in ("+", "-"):
            return ("unary", token, primary())
        if token == "(":
            value = comparison()
            if take() != ")":
                raise ValueError("Unbalanced formula")
            return value
        if token.startswith("["):
            return ("reference", token[1:-1])
        if token.startswith('"'):
            return ("literal", token[1:-1].replace('""', '"'))
        if token[0].isdigit():
            return ("literal", Decimal(token))
        if take() != "(":
            raise ValueError("Function call expected")
        arguments = []
        if tokens[index] != ")":
            while True:
                arguments.append(comparison())
                if tokens[index] != ";":
                    break
                take()
        if take() != ")":
            raise ValueError("Unbalanced function")
        if token.upper() not in ("IF", "SUM", "SUMIFS", "COUNTIFS", "LARGE", "INDEX", "MATCH"):
            raise ValueError(f"Unsupported generated function {token}")
        return ("call", token.upper(), arguments)

    def product():
        value = primary()
        while index < len(tokens) and tokens[index] in ("*", "/"):
            operator = take()
            value = ("binary", operator, value, primary())
        return value

    def addition():
        value = product()
        while index < len(tokens) and tokens[index] in ("+", "-"):
            operator = take()
            value = ("binary", operator, value, product())
        return value

    def comparison():
        value = addition()
        while index < len(tokens) and tokens[index] == "&":
            take()
            value = ("binary", "&", value, addition())
        if index < len(tokens) and tokens[index] in ("=", "<>", "<", ">", "<=", ">="):
            operator = take()
            value = ("binary", operator, value, addition())
        return value

    tree = comparison()
    if index != len(tokens):
        raise ValueError("Unconsumed formula tokens")
    return tree


def _address(value, default_sheet):
    match = ADDRESS.fullmatch(value)
    if not match:
        raise ValueError(f"Unsupported cell address {value}")
    name = (match[1].replace("''", "'") if match[1] else match[2]) or default_sheet
    column = 0
    for letter in match[3]:
        column = column * 26 + ord(letter) - 64
    return name, int(match[4]), column


def validate_formula_caches(path):
    """Evaluate formulas recursively against input cells, without an office install."""
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    cells, formulas = {}, {}
    for sheet in root.findall("./office:body/office:spreadsheet/table:table", NS):
        name = sheet.get(f"{{{NS['table']}}}name")
        row_index = 1
        for row in sheet.findall("table:table-row", NS):
            row_repeat = int(row.get(f"{{{NS['table']}}}number-rows-repeated", "1"))
            column = 1
            for cell in row:
                if cell.tag != f"{{{NS['table']}}}table-cell":
                    column += 1
                    continue
                column_repeat = int(cell.get(f"{{{NS['table']}}}number-columns-repeated", "1"))
                amount = cell.get(f"{{{NS['office']}}}value")
                value = Decimal(amount) if amount is not None else cell.get(f"{{{NS['office']}}}string-value", "".join(cell.itertext()))
                formula = cell.get(f"{{{NS['table']}}}formula")
                for r in range(row_index, row_index + row_repeat):
                    for c in range(column, column + column_repeat):
                        key = (name, r, c)
                        cells[key] = value
                        if formula:
                            formulas[key] = formula
                column += column_repeat
            row_index += row_repeat
    evaluated, visiting = {}, set()

    def scalar(key):
        if key in evaluated:
            return evaluated[key]
        if key in visiting:
            raise ValueError(f"Circular workbook formula at {key}")
        if key not in formulas:
            return cells.get(key, "")
        visiting.add(key)
        value = evaluate(_parse(formulas[key]), key[0])
        visiting.remove(key)
        evaluated[key] = value
        return value

    def evaluate(node, sheet):
        kind = node[0]
        if kind == "literal":
            return node[1]
        if kind == "reference":
            parts = node[1].split(":")
            first = _address(parts[0], sheet)
            if len(parts) == 1:
                return scalar(first)
            last = _address(parts[1], first[0])
            if first[0] != last[0]:
                raise ValueError("Cross-sheet range endpoints")
            return [scalar((first[0], row, column)) for row in range(first[1], last[1] + 1)
                    for column in range(first[2], last[2] + 1)]
        if kind == "unary":
            value = evaluate(node[2], sheet)
            return value if node[1] == "+" else -value
        if kind == "binary":
            left, right = evaluate(node[2], sheet), evaluate(node[3], sheet)
            operator = node[1]
            if operator == "+": return left + right
            if operator == "-": return left - right
            if operator == "*": return left * right
            if operator == "/": return left / right
            if operator == "&": return str(left) + str(right)
            if operator == "=": return left == right
            if operator == "<>": return left != right
            if operator == "<": return left < right
            if operator == ">": return left > right
            if operator == "<=": return left <= right
            if operator == ">=": return left >= right
        name, arguments = node[1], node[2]
        if name == "IF":
            return evaluate(arguments[1] if evaluate(arguments[0], sheet) else arguments[2], sheet)
        values = [evaluate(argument, sheet) for argument in arguments]
        if name == "SUM":
            return sum((amount for value in values for amount in (value if isinstance(value, list) else [value])
                        if isinstance(amount, Decimal)), Decimal(0))
        if name == "LARGE":
            numbers = sorted((amount for amount in values[0] if isinstance(amount, Decimal)), reverse=True)
            return numbers[int(values[1]) - 1]
        if name == "MATCH":
            if len(values) != 3 or values[2] != 0:
                raise ValueError("Only exact MATCH is used in generated workbooks")
            return Decimal(values[1].index(values[0]) + 1)
        if name == "INDEX":
            if len(values) != 2:
                raise ValueError("Only one-dimensional INDEX is used in generated workbooks")
            return values[0][int(values[1]) - 1]
        if name in ("SUMIFS", "COUNTIFS"):
            target = values[0] if name == "SUMIFS" else [Decimal(1)] * len(values[0])
            pairs = list(zip(values[1::2], values[2::2])) if name == "SUMIFS" else list(zip(values[::2], values[1::2]))
            if any(not isinstance(criteria, list) or len(criteria) != len(target) for criteria, _ in pairs):
                raise ValueError("Mismatched SUMIFS range")
            def matches(actual, expected):
                if not isinstance(expected, str):
                    return actual == expected
                match = re.fullmatch(r"(<=|>=|<>|<|>|=)(.*)", expected)
                if not match:
                    return actual == expected
                operator, threshold = match.groups()
                if isinstance(actual, Decimal):
                    threshold = Decimal(threshold)
                if operator == "<": return actual < threshold
                if operator == ">": return actual > threshold
                if operator == "<=": return actual <= threshold
                if operator == ">=": return actual >= threshold
                if operator == "<>": return actual != threshold
                return actual == threshold
            return sum((amount for index, amount in enumerate(target)
                        if isinstance(amount, Decimal) and all(matches(criteria[index], expected) for criteria, expected in pairs)), Decimal(0))
        raise ValueError("Unexpected formula node")

    with localcontext() as context:
        context.prec = 60
        for key, formula in formulas.items():
            computed = scalar(key)
            cached = cells[key]
            if isinstance(computed, Decimal) and isinstance(cached, Decimal):
                if abs(computed - cached) > Decimal("0.000000001") * max(Decimal(1), abs(computed)):
                    raise ValueError(f"Formula cache disagrees at {key}: {formula}")
            elif computed != cached:
                raise ValueError(f"Formula cache disagrees at {key}: {formula}")
    return {"independently_evaluated_formulas": len(formulas), "cache_mismatches": 0}
