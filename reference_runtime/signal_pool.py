"""Reuse visual actors instead of destroying PhysX objects at every phase.

Mitigation for the observed raycast SIGSEGV, not a proven engine-level fix.
The caller serializes scene mutations with the bridge. Inactive heads are parked
well below the drivable map, outside the 60m mapping/sensing neighborhood.
"""
import carla

STATES=('red','yellow','green','redleft','greenleft')


class PooledSignals:
    def parked(self,p,state):
        pose=self.pose(p)
        pose.location.z=-200.-STATES.index(state)*10
        return pose

    def set_state(self,p,state):
        if state not in STATES:raise ValueError(state)
        ident=p['regulatory_id']
        if not hasattr(self,'pool'):self.pool={}
        if ident not in self.pool:
            self.pool[ident]={}
            for label in STATES:
                self.pool[ident][label]=self.mesh('SM_KR_'+label,self.parked(p,label),'kr_signal_'+ident)
        if self.states.get(ident)==state:return self.heads[ident]
        old=self.heads.get(ident)
        if old is not None:old.set_transform(self.parked(p,self.states[ident]))
        new=self.pool[ident][state]
        new.set_transform(self.pose(p))
        self.heads[ident]=new;self.states[ident]=state
        return new

    def destroy(self):
        actors=[a for pool in getattr(self,'pool',{}).values() for a in pool.values()]+self.supports
        for actor in actors:
            if actor.is_alive:actor.destroy()
        self.pool={};self.heads.clear();self.supports.clear();self.states.clear()


def visible_signal(actor):
    return actor.attributes.get('role_name','').startswith('kr_signal_') and actor.get_transform().location.z>-100
