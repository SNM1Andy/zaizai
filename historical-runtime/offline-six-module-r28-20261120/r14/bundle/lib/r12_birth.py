def birth(path, identity, hazard, config, np):
    from al01.core import Individual, World
    from al01.instinct import Geometry, ReferenceCGL, FrozenBias
    from al01.integrated import IntegratedLife

    spec = config["world"]
    world = World(count=spec["count"], hazard=hazard, local=spec["local"])
    for name, pos in spec["positions"].items():
        world.objects[name]["position"] = list(pos)
    # Same calibration recipe as integrated_console.create_reference, which hardcodes a research ID.
    y, x = np.indices((64, 64))
    geometry = Geometry(np.cos(2 * np.pi * x / 64) + np.sin(4 * np.pi * y / 64))
    calibration_solver = ReferenceCGL(geometry, seed=991, dt=.01)
    rows = [calibration_solver.step() for _ in range(64)]
    weights = ((.1, -.1, 0., 0., .1, .2), (0., .1, -.1, .1, 0., -.1),
               (-.1, 0., .1, 0., .2, .1))
    calibration = FrozenBias.calibrate(rows,
        calibration_id='reference-independent-zero-drive-seed991-64steps-unvalidated-policy',
        weights=weights, beta=.1)
    return IntegratedLife(path, individual=Individual(world, individual_id=identity),
                          solver=ReferenceCGL(geometry, seed=config["field_seed"], dt=.01), calibration=calibration)
