"""Strategic rival selection for ZRE Core.

The module stays independent from iRacing. The bridge feeds it class-only timing
rows plus live pit/lap observations. AUTO chooses the closest meaningful class
rival; the UI may pin any candidate by CarIdx.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RivalSelection:
    idx: int | None
    mode: str

def _position(row):
    try:
        value=int(row.get("pos") or 0); return value if value>0 else 9999
    except (TypeError,ValueError): return 9999

def _gap(row):
    try:return abs(float(row.get("gapSeconds") or 0.0))
    except (TypeError,ValueError):return 9999.0

def select_rival(rows,player_idx,selected_idx=None):
    candidates=[row for row in rows if row.get("idx")!=player_idx and not row.get("isPlayer")]
    if not candidates:return RivalSelection(None,"auto")
    if selected_idx is not None:
        manual=next((row for row in candidates if row.get("idx")==selected_idx),None)
        if manual is not None:return RivalSelection(int(selected_idx),"manual")
    player=next((row for row in rows if row.get("idx")==player_idx or row.get("isPlayer")),None)
    player_pos=_position(player or {})
    def score(row):
        pos=_position(row);return (abs(pos-player_pos),0 if pos<player_pos else .2,_gap(row),pos)
    winner=min(candidates,key=score);return RivalSelection(int(winner["idx"]),"auto")

class RaceDirector:
    def __init__(self):
        self.selected_idx=None;self.gap_before_pit={};self.last_pit_state={}
    def set_selected(self,value):
        if value in (None,"","auto",-1,"-1"):self.selected_idx=None;return
        try:self.selected_idx=int(value)
        except (TypeError,ValueError):self.selected_idx=None
    def payload(self,rows,player_idx,pit_by_idx=None,lap_by_idx=None):
        pit_by_idx=pit_by_idx or {};lap_by_idx=lap_by_idx or {};selection=select_rival(rows,player_idx,self.selected_idx)
        candidates=[{"idx":row.get("idx"),"label":f"#{row.get('number','—')} · {row.get('driver','—')}","position":f"P{row.get('pos','—')}"} for row in rows if not row.get("isPlayer")]
        if selection.idx is None:
            return {"mode":selection.mode,"selectedIdx":None,"candidates":candidates,"confidence":"SIN RIVAL","rival":"—","position":"—","gap":"—","lastLap":"—","pit":"—","lap":"—","status":"Sin rival de clase disponible.","gapBefore":"—","netGap":"—"}
        rival=next(row for row in rows if row.get("idx")==selection.idx);on_pit=bool(pit_by_idx.get(selection.idx,False));was_on_pit=bool(self.last_pit_state.get(selection.idx,False))
        if on_pit and not was_on_pit:self.gap_before_pit[selection.idx]=rival.get("gap") or "—"
        self.last_pit_state[selection.idx]=on_pit;gap_before=self.gap_before_pit.get(selection.idx,"—");gap=rival.get("gap") or "—";status="EN BOXES" if on_pit else "EN PISTA";confidence="MANUAL" if selection.mode=="manual" else "AUTO"
        return {"mode":selection.mode,"selectedIdx":selection.idx,"candidates":candidates,"confidence":confidence,"rival":f"#{rival.get('number','—')} · {rival.get('driver','—')}","position":f"P{rival.get('pos','—')}","gap":gap,"lastLap":rival.get("lastLap") or "—","pit":status,"lap":f"V{lap_by_idx.get(selection.idx)}" if lap_by_idx.get(selection.idx) is not None else "—","status":f"{status} · {gap}","gapBefore":gap_before,"netGap":gap}
