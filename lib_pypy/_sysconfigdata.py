import imp

so = [s[0] for s in imp.get_suffixes() if s[2] == imp.C_EXTENSION]

if so:
    build_time_vars = {
        "SO": so[0]
    }
else:
    build_time_vars = {}
