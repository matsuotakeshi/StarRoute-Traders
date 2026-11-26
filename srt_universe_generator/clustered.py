"""Deterministic clustered placement on the existing integer chart."""
from starroute.generation_contract import separation, void_columns


def clustered_cells(params, rng):
    policy = params['distribution']
    width, height = params['width'], params['height']
    count = policy['cluster_count']
    radius = policy['cluster_radius']
    frontier = policy['frontier_planets']
    minimum = policy['min_distance']
    void = void_columns(params)
    points = []

    def place(candidates, quota):
        while candidates and quota:
            index = rng.below(len(candidates))
            point = candidates[index]
            candidates[index] = candidates[-1]
            candidates.pop()
            if all(separation(point, other) >= minimum for other in points):
                points.append(point)
                quota -= 1
        return quota == 0

    # Separate clusters into longitudinal sectors with independent centers.
    # Equal quotas bound the population of any one cluster.
    centers = []
    share, remainder = divmod(48 - frontier, count)
    for index in range(count):
        left, right = index * width // count, (index + 1) * width // count
        inner_left = left + (right - left) // 4
        inner_right = right - (right - left) // 4
        if inner_left >= inner_right:
            return None
        cx = inner_left + rng.below(inner_right - inner_left)
        cy = height // 4 + rng.below(height - 2 * (height // 4))
        centers.append((cx, cy))
        candidates = [
            (x, y)
            for x in range(max(left, cx - radius), min(right, cx + radius + 1))
            for y in range(max(0, cy - radius), min(height, cy + radius + 1))
            if x not in void and (x - cx)**2 + (y - cy)**2 <= radius**2
        ]
        if not place(candidates, share + (index < remainder)):
            return None

    # Frontier planets lie outside all cluster disks. They use the same
    # separation rule and cannot occupy the reserved empty corridor.
    candidates = [
        (x, y) for x in range(width) if x not in void for y in range(height)
        if all((x - cx)**2 + (y - cy)**2 > radius**2 for cx, cy in centers)
    ]
    if not place(candidates, frontier):
        return None
    return rng.shuffle(points)
