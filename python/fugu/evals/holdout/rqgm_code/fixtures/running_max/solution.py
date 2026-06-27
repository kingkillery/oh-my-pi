def running_max(xs):
    out = []
    cur = None
    for x in xs:
        cur = x if cur is None else max(cur, x)
        out.append(cur)
    return out
