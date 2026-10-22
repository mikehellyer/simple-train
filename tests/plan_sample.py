"""A small sample layout for tests: an oval with 45° corners, a passing
loop on the bottom, and a siding off the top ending in a buffer stop."""
from simple_train.core import track_plan as tp


def sample_plan() -> tp.Plan:
    plan = tp.Plan(name="Sample")
    T = tp.Tile
    pieces = [T(c, 3, tp.STRAIGHT, 0) for c in range(5, 21) if c != 12]
    pieces += [T(21, 3, tp.CURVE, 4), T(22, 4, tp.STRAIGHT, 3), T(23, 5, tp.CURVE, 3)]
    pieces += [T(23, r, tp.STRAIGHT, 2) for r in range(6, 9)]
    pieces += [T(23, 9, tp.CURVE, 2), T(22, 10, tp.STRAIGHT, 1), T(21, 11, tp.CURVE, 1)]
    pieces += [T(c, 11, tp.STRAIGHT, 0) for c in range(5, 21) if c not in (8, 17)]
    pieces += [T(4, 11, tp.CURVE, 0), T(3, 10, tp.STRAIGHT, 3), T(2, 9, tp.CURVE, 7)]
    pieces += [T(2, r, tp.STRAIGHT, 2) for r in range(6, 9)]
    pieces += [T(2, 5, tp.CURVE, 6), T(3, 4, tp.STRAIGHT, 1), T(4, 3, tp.CURVE, 5)]
    # The passing loop, below the bottom straight.
    pieces += [T(8, 11, tp.POINT_RIGHT, 4, address=1, name="Loop west"),
               T(9, 12, tp.STRAIGHT, 3), T(10, 13, tp.CURVE, 0)]
    pieces += [T(c, 13, tp.STRAIGHT, 0) for c in range(11, 15)]
    pieces += [T(15, 13, tp.CURVE, 1), T(16, 12, tp.STRAIGHT, 1),
               T(17, 11, tp.POINT_LEFT, 0, address=2, name="Loop east")]
    # A siding off the top.
    pieces += [T(12, 3, tp.POINT_RIGHT, 0, address=3, name="Siding"), T(11, 2, tp.STRAIGHT, 3),
               T(10, 1, tp.CURVE, 4), T(9, 1, tp.STRAIGHT, 0), T(8, 1, tp.STRAIGHT, 0), T(7, 1, tp.BUFFER, 0)]
    pieces += [T(9, 7, tp.LABEL, text="Fochabers")]
    for tile in pieces:
        plan.put(tile)
    return plan
