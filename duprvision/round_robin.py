"""Bounded, CPU-only doubles scheduling. History is never rewritten."""
from collections import Counter
from itertools import combinations

from ortools.sat.python import cp_model


def schedule(players, matches, courts, fixed=False):
    played, partners, opponents = Counter(), Counter(), Counter()
    for match in matches:
        if match['status'] == 'void':
            continue
        a, b = match['a'], match['b']
        played.update(a + b)
        partners.update(tuple(sorted(pair)) for team in (a, b) for pair in combinations(team, 2))
        opponents.update(tuple(sorted((x, y))) for x in a for y in b)
    eligible = [p for p in players if p['availability'] == 'ready']
    eligible.sort(key=lambda p: (played[p['id']], p['last_round'], p['id']))
    if fixed:
        teams = {}
        for p in players:
            if not p['team']:
                raise ValueError('Assign every player to a team before generating games.')
            teams.setdefault(p['team'], []).append(p)
        if any(len(team) != 2 for team in teams.values()):
            raise ValueError('Each fixed team needs exactly two players.')
        teams = [team for team in teams.values() if all(p['availability'] == 'ready' for p in team)]
        candidates = [(a, b) for a, b in combinations(teams, 2)
                      if not opponents[tuple(sorted((a[0]['id'], b[0]['id'])))]]
        if not candidates:
            raise ValueError('No unplayed matchup is available. Check attendance or finish this competition.')
        model = cp_model.CpModel()
        variables = [model.NewBoolVar(f'm{i}') for i in range(len(candidates))]
        for player in eligible:
            model.Add(sum(v for v, (a, b) in zip(variables, candidates)
                          if player in a + b) <= 1)
        model.Add(sum(variables) <= courts)
        # Court use comes first, then give teams with fewer games priority.
        model.Maximize(sum(v * (100000 - sum(played[p['id']] for p in a + b) * 100)
                           for v, (a, b) in zip(variables, candidates)))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 1
        solver.parameters.num_search_workers = 1
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise ValueError('A schedule is not available. Try again with fewer courts.')
        return [([p['id'] for p in a], [p['id'] for p in b])
                for v, (a, b) in zip(variables, candidates) if solver.Value(v)]

    count = min(courts, len(eligible) // 4)
    if not count:
        raise ValueError('Check in at least four players to generate a round.')
    # Equal playing time is prioritized before partner diversity. Reserve active slots
    # first so repeated pairing penalties can never force the same player to rest.
    selected = eligible[:count * 4]
    model = cp_model.CpModel()
    x = {(i, t): model.NewBoolVar(f'p{i}t{t}') for i in range(len(selected)) for t in range(count * 2)}
    for i in range(len(selected)):
        model.Add(sum(x[i, t] for t in range(count * 2)) == 1)
    for t in range(count * 2):
        model.Add(sum(x[i, t] for i in range(len(selected))) == 2)
    penalties = []
    for i, j in combinations(range(len(selected)), 2):
        key = tuple(sorted((selected[i]['id'], selected[j]['id'])))
        for t in range(count * 2):
            if partners[key]:
                together = model.NewBoolVar(f'partner{i}_{j}_{t}')
                model.Add(together >= x[i, t] + x[j, t] - 1)
                penalties.append(together * partners[key] * 10)
        if opponents[key]:
            for t in range(0, count * 2, 2):
                for left, right in ((i, j), (j, i)):
                    opposed = model.NewBoolVar(f'opp{left}_{right}_{t}')
                    model.Add(opposed >= x[left, t] + x[right, t + 1] - 1)
                    penalties.append(opposed * opponents[key])
    model.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        teams = [[p['id'] for i, p in enumerate(selected) if solver.Value(x[i, t])]
                 for t in range(count * 2)]
    else:
        # A valid bounded fallback preserves participation even if optimization times out.
        teams = [[p['id'] for p in selected[i:i + 2]] for i in range(0, len(selected), 2)]
    return [(teams[i], teams[i + 1]) for i in range(0, len(teams), 2)]
