"""Small session-scoped manual pit log. Never labels remote fuel as measured."""
from dataclasses import dataclass, field

@dataclass
class SpotterControl:
    events: list = field(default_factory=list)
    seen: set = field(default_factory=set)
    pit_pending: bool = False
    last_stop_lap: int | None = None
    fuel_liters: float | None = None
    fuel_lap: int | None = None
    fuel_source: str = 'NO DISPONIBLE'
    manual_driver: str | None = None
    stint_started_lap: int | None = None

    def pit_transition(self, entered, lap):
        if entered:
            self.pit_pending=True
            self.last_stop_lap=lap
            self.fuel_source='PENDIENTE' # Pit road never implies refueling.
            self.fuel_liters=None
            self.fuel_lap=None

    def apply(self, event, *, lap, tank_capacity=None, projected_fuel=None):
        kind=event.get('action')
        if kind not in ('stop','no_fuel','fill','add_fuel','driver','new_stint'):
            return 'Acción desconocida'
        event_id=str(event.get('id') or '')
        if not event_id or event_id in self.seen:return None
        if kind=='fill' and (tank_capacity is None or tank_capacity<=0):return 'Configura TANQUE L para llenar'
        if kind=='add_fuel':
            try:added=float(event.get('liters'))
            except (TypeError,ValueError):return 'Introduce litros válidos'
            if not 0<added<=300:return 'Introduce litros válidos'
            if projected_fuel is None:return 'No hay referencia de fuel: usa LLENAR o configura una lectura'
        if kind=='stop':
            self.pit_pending=True;self.last_stop_lap=lap;self.fuel_source='PENDIENTE'
        elif kind=='fill':
            self.fuel_liters=float(tank_capacity);self.fuel_lap=lap;self.fuel_source='MANUAL · ESTIMADO';self.pit_pending=False
        elif kind=='add_fuel':
            self.fuel_liters=min(float(tank_capacity),projected_fuel+added) if tank_capacity else projected_fuel+added
            self.fuel_lap=lap;self.fuel_source='MANUAL · ESTIMADO';self.pit_pending=False
        elif kind=='no_fuel':
            if projected_fuel is not None:self.fuel_liters=projected_fuel;self.fuel_lap=lap;self.fuel_source='MANUAL · ESTIMADO'
            else:self.fuel_source='PENDIENTE'
            self.pit_pending=False
        elif kind=='driver':
            name=str(event.get('driver') or '').strip()[:60]
            if not name:return 'Selecciona piloto'
            self.manual_driver=name
        elif kind=='new_stint':
            self.stint_started_lap=lap;self.pit_pending=False
            name=str(event.get('driver') or '').strip()[:60]
            if name:self.manual_driver=name
        self.seen.add(event_id)
        self.events.append({'id':event_id,'action':kind,'lap':lap,'liters':event.get('liters'), 'driver':event.get('driver')})
        return None

    def fuel_at(self,completed,consumption):
        if self.fuel_liters is None or self.fuel_lap is None or completed is None:return None
        if completed<self.fuel_lap:return None
        if consumption is None or consumption<=0:return self.fuel_liters if completed==self.fuel_lap else None
        return max(0,self.fuel_liters-(completed-self.fuel_lap)*consumption)
