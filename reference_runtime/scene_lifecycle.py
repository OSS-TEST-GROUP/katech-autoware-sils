"""Distinguish an explicitly requested scene shutdown from a live clock failure."""


def wait_scene_tick(world, running):
    try:
        snapshot = world.wait_for_tick(10)
    except RuntimeError as error:
        message = str(error)
        expected_timeout = message.startswith('time-out of ') and 'while waiting for the simulator' in message
        if not running() and expected_timeout:
            return None
        raise
    return snapshot if running() else None
