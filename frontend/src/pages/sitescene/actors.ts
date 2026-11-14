import { projectApiUrl } from "../../api/workspace";
import type { Flag, Plan, RecordEntry, StartCheck, Task, Machine } from '../../api/client';

export interface ActorSource { id: string; label: string; href: string }
export interface SiteActor {
  id: string;
  kind: 'crew' | 'robot' | 'drone' | 'crane' | 'truck';
  label: string;
  unit: string | null;
  motion: boolean;
  reason: string;
  sources: ActorSource[];
  signature: string;
}
export interface ActorInput {
  day: string; units: string[]; plan: Plan; flags: Flag[]; checks: StartCheck[]; record: RecordEntry[];
  machines?: Machine[];
}
const current = (task: Task, day: string) => task.status !== 'done' && task.start.slice(0,10) <= day && day <= task.end.slice(0,10);
const planSource = (id: string, label: string): ActorSource => ({id,label,href:'/plan'});
const checkSource = (check: StartCheck): ActorSource => ({id:check.id,label:`Start check ${check.id}`,href:'/robot'});

/** Project assignments, not measured positions. Missing permission or a target never creates movement. */
export function actorsFor(input: ActorInput): SiteActor[] {
  const {day, plan, flags, record, units} = input;
  const tasks = (plan.tasks ?? []).filter(task=>current(task,day));
  const checks = input.checks.filter(check=>check.checked_at.slice(0,10)===day)
    .map((check,index)=>({check,index})).sort((a,b)=>b.check.checked_at.localeCompare(a.check.checked_at)||b.index-a.index).map(row=>row.check);
  const latest = checks.filter((check,index)=>checks.findIndex(other=>other.asked_by===check.asked_by)===index);
  const actors: SiteActor[] = [];
  function add(actor: Omit<SiteActor,'signature'>) {
    actors.push({...actor,signature:JSON.stringify([actor.id,actor.unit,actor.motion,actor.reason,actor.sources.map(s=>s.id)])});
  }
  function hold(task: Task | undefined, unit: string | null): {reason:string;source:ActorSource} | null {
    const flag = flags.find(flag=>flag.status==='held' && task && (
      flag.affected?.task ? flag.affected.task===task.id
        : flag.affected?.crew===task.crew && flag.affected?.unit===unit));
    if(flag) return {reason:flag.title,source:{id:flag.id,label:flag.title,href:`/flags/${encodeURIComponent(flag.id)}`}};
    if(task?.status==='on_hold') return {reason:'The plan puts this task on hold.',source:planSource(task.id,task.name)};
    return null;
  }
  for(const task of tasks) {
    if(!task.unit || !units.includes(task.unit)) continue;
    const stop = hold(task,task.unit);
    const check = checks.find(check=>check.task_id===task.id);
    const refused = check && check.allowed!=='yes';
    add({id:`crew-${task.id}`,kind:'crew',label:task.crew,unit:task.unit,motion:!stop&&!refused,
      reason:stop?.reason ?? (refused ? check.summary : `Assigned to ${task.name} today.`),
      sources:[planSource(task.id,`${task.id}: ${task.name}`),...(stop?[stop.source]:[]),...(check?[checkSource(check)]:[])]});
  }
  for(const check of latest) {
    const kind = /drone/i.test(check.asked_by) ? 'drone' : /robot/i.test(check.asked_by) ? 'robot' : null;
    if(!kind) continue;
    const task = (plan.tasks??[]).find(task=>task.id===check.task_id);
    const target = check.unit ?? task?.unit ?? null;
    const unit = target && units.includes(target) ? target : null;
    const stop = hold(task,unit);
    add({id:`machine-${check.asked_by}`,kind,label:check.asked_by,unit,
      motion:check.allowed==='yes'&&!stop&&!!unit,
      reason:stop?.reason ?? (!unit?'Unit target unavailable in the start check.':check.summary),
      sources:[checkSource(check),...(stop?[stop.source]:[]),...(task?[planSource(task.id,task.name)]:[])]});
  }
  for (const machine of input.machines ?? []) {
    if ((machine.kind !== 'robot' && machine.kind !== 'drone') || latest.some(check => check.asked_by === machine.id)) continue;
    const unit = (machine.units ?? []).find(unit => units.includes(unit)) ?? null;
    add({id:`machine-${machine.id}`, kind:machine.kind, label:machine.name, unit, motion:false,
      reason:'Registered and parked. No start clearance has been recorded.',
      sources:[{id:machine.id,label:'Equipment registration',href:'/machines'}]});
  }
  for(const resource of plan.resources??[]) {
    if(resource.date.slice(0,10)>day || resource.planned<=0) continue;
    const flag = flags.filter(flag=>flag.affected?.resource===resource.id).sort((a,b)=>b.raised_at.localeCompare(a.raised_at))[0];
    const source = planSource(resource.id,`${resource.id}: ${resource.item}`);
    if(resource.kind==='equipment' && /crane/i.test(resource.item)) {
      const task = tasks.find(task=>task.id===flag?.affected?.task) ?? tasks.find(task=>/lift/i.test(task.name));
      const unit = task?.unit && units.includes(task.unit) ? task.unit : null;
      const stop = hold(task,unit);
      const late = !!flag?.affected?.actual_date && flag.affected.actual_date.slice(0,10)>day;
      add({id:`crane-${resource.id}`,kind:'crane',label:resource.item,unit,
        motion:resource.date.slice(0,10)===day&&!!unit&&!stop&&!late,
        reason:stop?.reason ?? (late ? flag.summary : !unit?'Lift unit unavailable in the plan.':resource.date.slice(0,10)!==day?'No crane use planned for today.':`Planned lift: ${task!.name}.`),
        sources:[source,...(task?[planSource(task.id,task.name)]:[]),...(stop?[stop.source]:[]),...(late?[{id:flag.id,label:flag.title,href:`/flags/${flag.id}`}]:[])]});
    }
    if(resource.kind==='delivery') {
      const entry = record.filter(entry=>(entry.source_event_ids??[]).length>0 && (
        (entry.refs?.fact_type==='delivery_actual' && !!entry.refs.fact
          && entry.refs.item?.trim().toLowerCase()===resource.item.trim().toLowerCase()
          && entry.refs.resource_date===resource.date.slice(0,10))
        || (flag && entry.refs?.flag===flag.id && (entry.source_event_ids??[]).some(id=>(flag.evidence??[]).some(evidence=>evidence.event_id===id)))
      )).sort((a,b)=>b.at.localeCompare(a.at))[0];
      const late = !!flag?.affected?.actual_date && flag.affected.actual_date.slice(0,10)>day;
      const stopped = late || flag?.status==='held';
      const reportedToday = entry?.at.slice(0,10)===day;
      const sources = [source];
      if(entry) for(const id of entry.source_event_ids??[]) sources.push({id,label:`Delivery source ${id}`,href:projectApiUrl(`/api/events/${encodeURIComponent(id)}`)});
      add({id:`truck-${resource.id}`,kind:'truck',label:resource.item,unit:null,motion:!!reportedToday&&!stopped,
        reason:stopped ? flag!.summary : reportedToday?'Delivery report recorded. Schematic route, not a measured arrival.':entry?'Earlier delivery report; no new activity recorded today.':resource.date.slice(0,10)<day?'Waiting at the gate: planned delivery date passed without a sourced report.':'Waiting at the gate: no sourced delivery record.',sources});
    }
  }
  return actors;
}
