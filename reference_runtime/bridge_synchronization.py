"""Session-only overlay: serialize stationary RViz relocation with sensor ticks.

This closes a client-side concurrency gap; it is not proof of a PhysX fix.
"""
import ast


def protect_initialpose(source):
    signature = '    def initialpose_callback(self, data):'
    decorator = '    @scene_transaction()\n'
    if source.count(signature) != 1:
        raise ValueError('Expected exactly one initialpose callback')
    if decorator + signature not in source:
        source = source.replace(signature, decorator + signature)
    imported = 'from simulation_lock import scene_transaction\n'
    if imported not in source:
        if source.count('import threading\n') != 1:
            raise ValueError('Unexpected bridge imports')
        source = source.replace('import threading\n', 'import threading\n' + imported)
    ast.parse(source)
    return source
