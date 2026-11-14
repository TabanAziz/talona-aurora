import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { Async } from "../../components/States";
import { formatDay } from "../../components/format";
import { Message } from "./Message";
import { buildThreads, channelName, dayLabel, preview, searchableText, type Thread } from "./threads";
import "./crew.css";

const POLL_MS = 3000;

async function loadThreads(): Promise<Thread[]> {
  const [project, events, outbox, answers, flags, record] = await Promise.all([
    api.project(), api.events(), api.outbox(), api.answers(), api.flags(), api.record(),
  ]);
  return buildThreads({ crews: project.crews, events, outbox, answers, flags, record });
}

function ThreadView({ thread, open, search, onBack }: { thread: Thread; open: boolean; search: string; onBack: () => void }) {
  const [day, setDay] = useState("");
  const [person, setPerson] = useState("");
  const [programmeOpen, setProgrammeOpen] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const requested = params.get("event") || params.get("message");
  const setup = thread.key === "setup";
  const query = search.trim().toLocaleLowerCase();
  const days = [...new Set(thread.items.map(item => item.at.slice(0, 10)))].reverse();
  const items = thread.items.filter(item => (!day || item.at.startsWith(day)) && (!person || item.people.includes(person)) && (!query || searchableText(item).toLocaleLowerCase().includes(query)));
  const programme = items.filter(item => item.kind === "in" && item.id.startsWith("workspace-task-"));
  const visible = setup ? items.filter(item => !(item.kind === "in" && item.id.startsWith("workspace-task-"))) : items;
  const people = [...new Set(thread.items.flatMap(item => item.people))].filter(name => name !== "Aurora" && name !== "Project setup" && name !== "Reviewed project import").sort();
  const jumpLatest = () => body.current?.scrollTo({ top: body.current.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });

  useEffect(() => {
    if (requested) return;
    const list = body.current;
    if (!list || setup) return;
    const latestDay = thread.items.at(-1)?.at.slice(0, 10);
    if (!latestDay) return;
    const firstRecent = [...list.querySelectorAll<HTMLElement>("[data-at]")].find(element => element.dataset.at?.startsWith(latestDay));
    if (firstRecent) list.scrollTop += firstRecent.getBoundingClientRect().top - list.getBoundingClientRect().top;
  }, [thread.key, open]);

  useEffect(() => {
    const target = location.hash ? decodeURIComponent(location.hash.slice(1)) : requested ? `crew-event-${requested}` : "";
    if (!target) return;
    setDay("");
    setPerson("");
    if (requested?.startsWith("workspace-task-")) setProgrammeOpen(true);
    const frame = requestAnimationFrame(() => document.getElementById(target)?.scrollIntoView({ block: "center" }));
    return () => cancelAnimationFrame(frame);
  }, [location.hash, location.search, open, programmeOpen]);

  return <section className="crew-chat" data-testid="crew-thread" data-open-flag={thread.hasOpenFlag} aria-label={`Conversation: ${thread.name}`}>
    <header className="crew-chat-head">
      <button className="crew-back" onClick={onBack} type="button" aria-label="Back to conversations">‹</button>
      <span className={`crew-avatar ${setup ? "crew-avatar-group" : "crew-avatar-aurora"}`} aria-hidden="true">{setup ? "P" : "A"}</span>
      <div className="crew-chat-title"><h2>{thread.name}</h2><p className="muted small">{setup ? "Reviewed inputs, drawings and imported programme" : "Site messages, Aurora’s replies and recorded actions"}</p></div>
      {!setup && <span className="crew-live-label">Updates automatically</span>}
    </header>
    <div className="crew-toolbar">
      <label className="crew-date-control">Date<select value={day} onChange={event => setDay(event.target.value)} data-testid="crew-date-filter"><option value="">All dates</option>{days.map(date => <option key={date} value={date}>{dayLabel(date)}</option>)}</select></label>
      {people.length > 0 && <label className="crew-date-control">People / crew<select value={person} onChange={event => setPerson(event.target.value)} data-testid="crew-person-filter"><option value="">Everyone</option>{people.map(name => <option key={name} value={name}>{name}</option>)}</select></label>}
      <span className="muted small">{items.length} {setup ? "source records" : "messages & actions"} · UTC</span>
      <button type="button" className="crew-latest" onClick={jumpLatest}>Latest</button>
    </div>
    <div className="crew-chat-body" ref={body} data-testid="crew-message-list">
      {setup && <div className="crew-context-note"><strong>Project setup stays here.</strong><p>Imported programme records are reference material. They do not confirm that work has started or finished.</p><div className="row"><Link to="/drawings">View drawings</Link><Link to="/plan">View schedule</Link></div></div>}
      {!items.length && <div className="crew-empty"><h3>{query || day || person ? "No matching messages" : setup ? "No imported setup sources" : "The team conversation starts here"}</h3><p className="muted">{query || day || person ? "Try another search, date or person." : setup ? "Reviewed project inputs will appear here after import." : "Send a message in your project Telegram group or inbox. Incoming messages appear here with Aurora’s actual replies, confirmations and results."}</p></div>}
      <ol className="crew-message-items" aria-label="Messages, oldest to newest">{visible.map((item, index) => <Message key={`${item.kind}-${item.id}`} item={item} showDay={!visible[index - 1] || visible[index - 1].at.slice(0, 10) !== item.at.slice(0, 10)} />)}</ol>
      {programme.length > 0 && <details className="crew-programme" open={programmeOpen} onToggle={event => setProgrammeOpen(event.currentTarget.open)}><summary>Imported programme <span className="muted">{programme.length} source records</span></summary><p className="muted small">The reviewed schedule inputs, kept separate from team communication.</p>{programmeOpen && <ol className="crew-message-items" aria-label="Imported programme source records">{programme.map((item, index) => <Message key={item.id} item={item} showDay={!programme[index - 1] || programme[index - 1].at.slice(0, 10) !== item.at.slice(0, 10)} />)}</ol>}</details>}
    </div>
    <p className="crew-readonly muted small">{setup ? "Reference conversation · source files and imported records" : "Reply in the original channel. Delivery status is shown on every Aurora message."}</p>
  </section>;
}

function Mailbox({ threads }: { threads: Thread[] }) {
  const [selected, setSelected] = useState("team");
  const [search, setSearch] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [params, setParams] = useSearchParams();
  const sourceEvent = params.get("event") || params.get("message");
  const conversation = params.get("conversation");
  const explicitlyOpened = threads.some(thread => thread.key === conversation);
  const linked = sourceEvent ? threads.find(thread => thread.items.some(item => item.id === sourceEvent)) : undefined;
  const active = linked ?? threads.find(thread => thread.key === (params.get("conversation") || selected)) ?? threads[0];
  const query = search.trim().toLocaleLowerCase();
  return <div className={`crew-workspace${mobileOpen || linked || explicitlyOpened ? " crew-mobile-open" : ""}`}>
    <aside className="crew-mailbox" aria-label="Conversations">
      <div className="crew-mailbox-search"><label className="crew-label" htmlFor="crew-search">Find a message</label><input id="crew-search" type="search" aria-label="Search messages" value={search} onChange={event => setSearch(event.target.value)} placeholder="Person, crew or message" data-testid="crew-search" /></div>
      <div className="crew-conversations"><h2 className="crew-group-title">Conversations<span>2</span></h2>
        {threads.map(thread => {
          const last = thread.items.at(-1);
          const match = query ? thread.items.find(item => searchableText(item).toLocaleLowerCase().includes(query)) : undefined;
          const matches = query ? thread.items.filter(item => searchableText(item).toLocaleLowerCase().includes(query)).length : 0;
          return <button key={thread.key} type="button" className={`crew-conversation${thread.key === active.key ? " is-selected" : ""}`} aria-pressed={thread.key === active.key} data-testid="crew-conversation" onClick={() => { setParams(match ? { conversation: thread.key, message: match.id } : { conversation: thread.key }); setSelected(thread.key); setMobileOpen(true); }}>
            <span className={`crew-avatar ${thread.key === "team" ? "crew-avatar-aurora" : "crew-avatar-person"}`} aria-hidden="true">{thread.key === "team" ? "A" : "P"}</span>
            <span className="crew-conversation-copy"><span className="crew-conversation-top"><strong>{thread.name}</strong>{last && <time dateTime={last.at} title={last.at}>{formatDay(last.at)}</time>}</span><span className="crew-conversation-name">{query ? `${matches} matching messages` : thread.key === "team" ? thread.channels.map(channelName).join(", ") || "Site communication" : "Imports & reference material"}{thread.hasOpenFlag && <span className="crew-attention">Open issue</span>}</span><span className="crew-preview" title={preview(match ?? last)}>{preview(match ?? last)}</span><span className="crew-count">{thread.items.length} {thread.key === "team" ? "messages & actions" : "source records"}</span></span>
          </button>;
        })}
      </div>
      <p className="crew-mailbox-note muted small">The conversation and the result, together. Project imports are kept in their own space.</p>
    </aside>
    <ThreadView key={active.key} thread={active} search={search} open={mobileOpen || !!linked || explicitlyOpened} onBack={() => { setSelected(active.key); setMobileOpen(false); setParams({}); }} />
  </div>;
}

export function Crew() {
  const threads = useQuery(loadThreads, [], { poll: POLL_MS, empty: [] as Thread[] });
  return <div className="crew" data-testid="crew-view"><header className="crew-page-head"><h1>Messages</h1><p className="muted">Your team, Aurora, and what happened next.</p></header><Async query={threads} rows={4} empty="No messages yet. Connect a channel to see site conversations here.">{items => <Mailbox threads={items} />}</Async></div>;
}
