"""Profile dependency calculations from the server catalogue (no embedded rules)."""


def closure(selected: set[int], dependencies: dict[int, set[int]]) -> set[int]:
    result = set(selected)
    pending = list(selected)
    while pending:
        for required in dependencies.get(pending.pop(), set()) - result:
            result.add(required)
            pending.append(required)
    return result


def dependents(identifier: int, selected: set[int], dependencies: dict[int, set[int]]) -> set[int]:
    return {item for item in selected - {identifier}
            if identifier in closure({item}, dependencies)}
