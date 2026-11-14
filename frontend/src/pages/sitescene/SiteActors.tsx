import type { SiteActor } from './actors';
import './sitescene.css';

export function SiteStops({actors}:{actors:SiteActor[]}) {
  const stopped=actors.filter(actor=>!actor.motion);
  if(!stopped.length) return null;
  return <aside className="sitescene-stops" data-testid="sitescene-stops" aria-label="Stopped on site">
    <h2>Stopped on site</h2>
    {stopped.map(actor=><section className="sitescene-callout" key={actor.id} data-testid="sitescene-stop-callout" data-actor-id={actor.id}>
      <div className="row"><svg className="sitescene-stop-sign" viewBox="0 0 32 32" aria-hidden="true"><path d="M10 1h12l9 9v12l-9 9H10l-9-9V10z" fill="currentColor"/></svg><strong>STOP{actor.unit?` · ${actor.unit}`:''}</strong></div>
      <strong>{actor.label}</strong>
      <p>{actor.reason}</p>
    </section>)}
  </aside>;
}

export function SiteActors({actors}:{actors:SiteActor[]}) {
  return <section className="sitescene" data-testid="sitescene-view" aria-labelledby="sitescene-heading">
    <h2 id="sitescene-heading">What moved what</h2>
    <p className="muted small">Schematic assignment transitions from the record, not live positions. Stopped actors stay still. The laydown area is schematic.</p>
    {!actors.length ? <p>No current task, delivery report or machine check supplies an actor.</p> :
    <ul className="sitescene-actors">{actors.map(actor=><li key={actor.id} data-testid="sitescene-actor" data-actor-id={actor.id} data-kind={actor.kind} data-moving={actor.motion}>
      <div><strong>{actor.label}</strong> <span className={actor.motion?'sitescene-moving':'sitescene-stop'}>{actor.motion?'Assigned transition':'STOP'}</span>{actor.unit&&<span> · {actor.unit}</span>}</div>
      <p>{actor.reason}</p>
      <ul className="sitescene-sources">{actor.sources.map(source=><li key={source.id}><a href={source.href}>{source.label}</a></li>)}</ul>
    </li>)}</ul>}
  </section>;
}
