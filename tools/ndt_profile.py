"""SILS optimizer step tuning, without altering localization acceptance gates."""
from copy import deepcopy


def bounded_step_profile(configuration):
    result=deepcopy(configuration)
    try:
        ndt=result['/**']['ros__parameters']['ndt']
        if ndt['step_size'] not in (.1,.05) or ndt['trans_epsilon']!=.01:
            raise ValueError('Unqualified NDT optimizer baseline')
        ndt['step_size']=.05
    except (KeyError,TypeError) as error:
        raise ValueError('Incomplete NDT optimizer profile') from error
    return result
