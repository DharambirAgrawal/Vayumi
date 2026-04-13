from __future__ import annotations

import json
from typing import Iterable


def data_analyzer(numbers: Iterable[float]) -> str:
    data = [float(n) for n in numbers]
    if not data:
        return "ERROR: numbers cannot be empty"
    total = sum(data)
    avg = total / len(data)
    return json.dumps({"count": len(data), "sum": total, "avg": avg, "min": min(data), "max": max(data)})
