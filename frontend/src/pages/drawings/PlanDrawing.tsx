import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { useQuery } from "../../api/useQuery";
import { Async } from "../../components/States";
import { loadGeometry, type Geometry, type Room, type Wall } from "../../components/plan3d/geometry";
import { splitFloors, type FloorPlan } from "../../components/plan3d/floors";
import "./plan-drawing.css";

export function PlanDrawing({ url, zoom }: { url: string; zoom: number }) {
  const geometry = useQuery(() => loadGeometry(url), [url]);
  const project = useQuery(api.project, []);
  return <Async query={geometry} rows={6}>{data => <FloorDrawing geometry={data} project={project.data?.name ?? "Project drawing"} zoom={zoom} />}</Async>;
}

function FloorDrawing({ geometry, project, zoom }: { geometry: Geometry; project: string; zoom: number }) {
  const floors = useMemo(() => splitFloors(geometry), [geometry]);
  const [level, setLevel] = useState(floors[0]?.level ?? "");
  const [selectedRoom, setSelectedRoom] = useState<number | null>(null);
  const floor = floors.find(floor => floor.level === level) ?? floors[0];
  return <div className="technical-plan-view">
    <div className="technical-plan-toolbar"><span>Geometry drawing · dimensions in mm</span>{floors.length > 1 && <label>Floor<select value={floor.level} onChange={event => { setLevel(event.target.value); setSelectedRoom(null); }}>{floors.map(item => <option key={item.level} value={item.level}>Level {item.level}</option>)}</select></label>}</div>
    <div className="technical-plan-workspace">
      <div className="technical-plan-scroll" tabIndex={0} aria-label="Floor plan, scroll to pan"><Sheet geometry={geometry} floor={floor} project={project} zoom={zoom} selectedRoom={selectedRoom} /></div>
      {floor.rooms.length > 0 && <aside className="plan-room-index" aria-label="Room index">
        <div className="plan-room-index-heading"><strong>Room index</strong><span>{floor.rooms.length} rooms · Level {floor.level || "not specified"}</span><p>Small rooms use markers. Select a room to locate it on the drawing.</p></div>
        <ol>{floor.rooms.map((room, index) => <li key={`${room.label}-${index}`}><button type="button" aria-pressed={selectedRoom === index} onClick={() => setSelectedRoom(selectedRoom === index ? null : index)}><span className="plan-room-index-number">{index + 1}</span><span>{room.label}</span></button></li>)}</ol>
      </aside>}
    </div>
  </div>;
}

function Sheet({ geometry, floor, project, zoom, selectedRoom }: { geometry: Geometry; floor: FloorPlan; project: string; zoom: number; selectedRoom: number | null }) {
  const walls = floor.walls;
  const x0 = walls.length ? Math.min(...walls.map(wall => Math.min(wall.x1, wall.x2))) : 0;
  const y0 = walls.length ? Math.min(...walls.map(wall => Math.min(wall.y1, wall.y2))) : 0;
  const x1 = walls.length ? Math.max(...walls.map(wall => Math.max(wall.x1, wall.x2))) : geometry.width;
  const y1 = walls.length ? Math.max(...walls.map(wall => Math.max(wall.y1, wall.y2))) : geometry.height;
  const scale = Math.min(820 / Math.max(1, x1-x0), 520 / Math.max(1, y1-y0));
  const ox = 90+(820-(x1-x0)*scale)/2, oy = 150+(520-(y1-y0)*scale)/2;
  const px = (x: number) => ox+(x-x0)*scale;
  const py = (y: number) => oy+(y-y0)*scale;
  const changed = new Set(geometry.changed ?? []);
  const wallById = new Map(walls.map(wall => [wall.id, wall]));
  const barMm = [100,200,500,1000,2000,5000,10000,20000].filter(size => size*scale <= 150).at(-1) ?? 100;
  const barWidth = barMm*scale;
  const titleLines = wrap(project, 18);
  const roomLabels = layoutRoomLabels(floor.rooms, walls, scale, zoom);
  return <svg viewBox="0 0 1200 820" className="technical-plan-sheet" style={{ width: `${zoom*100}%` }} role="img" aria-label={`${project}, ${geometry.sheet} Rev ${geometry.revision}, level ${floor.level || "not specified"}. Source wall coordinates, doors and windows.`} data-testid="technical-plan">
    <rect x="1" y="1" width="1198" height="818" className="plan-paper" />
    <text x="56" y="48" className="plan-brand">AURORA</text><text x="56" y="76" className="plan-subtitle">{geometry.sheet} · LEVEL {floor.level || "—"} · REV {geometry.revision}</text>
    {[0,1,2,3,4].map(index => {
      const x = x0+(x1-x0)*index/4;
      return <g key={`x${index}`}><line x1={px(x)} y1="115" x2={px(x)} y2="690" className="plan-grid" /><text x={px(x)} y="710" textAnchor="middle" className="plan-coordinate">{Math.round(x).toLocaleString("en-GB")}</text></g>;
    })}
    {[0,1,2,3].map(index => {
      const y = y0+(y1-y0)*index/3;
      return <line key={`y${index}`} x1="66" y1={py(y)} x2="934" y2={py(y)} className="plan-grid" />;
    })}
    <g className="plan-dimension"><line x1={px(x0)} y1="111" x2={px(x1)} y2="111" /><line x1={px(x0)} y1="101" x2={px(x0)} y2="123" /><line x1={px(x1)} y1="101" x2={px(x1)} y2="123" /><text x={(px(x0)+px(x1))/2} y="101" textAnchor="middle">{Math.round(x1-x0).toLocaleString("en-GB")} mm</text><line x1="51" y1={py(y0)} x2="51" y2={py(y1)} /><text transform={`translate(38 ${(py(y0)+py(y1))/2}) rotate(-90)`} textAnchor="middle">{Math.round(y1-y0).toLocaleString("en-GB")} mm</text></g>
    {walls.map(wall => <line key={wall.id} x1={px(wall.x1)} y1={py(wall.y1)} x2={px(wall.x2)} y2={py(wall.y2)} className={changed.has(wall.id) ? "plan-wall plan-wall-changed" : "plan-wall"} strokeWidth={Math.max(wall.thickness*scale, wall.kind === "exterior" ? 6 : 3)} />)}
    {floor.openings.map((opening,index) => {
      const wall = wallById.get(opening.wall);
      if (!wall) return null;
      const length = Math.hypot(wall.x2-wall.x1, wall.y2-wall.y1);
      if (!length) return null;
      const ux=(wall.x2-wall.x1)/length, uy=(wall.y2-wall.y1)/length;
      const ax=px(wall.x1+ux*opening.offset), ay=py(wall.y1+uy*opening.offset);
      const bx=px(wall.x1+ux*(opening.offset+opening.width)), by=py(wall.y1+uy*(opening.offset+opening.width));
      const width=opening.width*scale, inset=Math.max(wall.thickness*scale,4)/2;
      const cx=ax-uy*width, cy=ay+ux*width;
      return <g key={`${opening.wall}-${index}`}><line x1={ax} y1={ay} x2={bx} y2={by} className="plan-opening" strokeWidth={Math.max(wall.thickness*scale,6)+2} />{opening.kind === "window" ? <g className="plan-window"><line x1={ax-uy*inset} y1={ay+ux*inset} x2={bx-uy*inset} y2={by+ux*inset} /><line x1={ax+uy*inset} y1={ay-ux*inset} x2={bx+uy*inset} y2={by-ux*inset} /><line x1={ax} y1={ay} x2={bx} y2={by} /></g> : <g className="plan-door"><line x1={ax} y1={ay} x2={cx} y2={cy} /><path d={`M${bx},${by} A${width},${width} 0 0 1 ${cx},${cy}`} /></g>}</g>;
    })}
    {roomLabels.map(({ room, index, lines, fontSize, width, height, marker }) => {
      const selected = selectedRoom === index;
      return <g key={`${room.label}-${index}`} transform={`translate(${px(room.x)} ${py(room.y)})`} className={selected ? "plan-room plan-room-selected" : "plan-room"} data-room-label={room.label} data-label-mode={marker ? "marker" : "text"}>
        <title>{index + 1}. {room.label} ({Math.round(room.x)}, {Math.round(room.y)} mm)</title>
        {selected && <circle r={Math.max(width, height) / 2 + 5} className="plan-room-selection" />}
        {marker && !lines.length ? <circle r={width / 2} className="plan-room-marker" /> : <>
          <rect x={-width/2} y={-height/2} width={width} height={height} rx={marker ? height / 2 : 3} className="plan-room-label-bg" />
          {lines.map((line,i) => <text key={i} x="0" y={(i-(lines.length-1)/2)*fontSize*1.2} dominantBaseline="central" textAnchor="middle" className="plan-room-label" style={{ fontSize }}>{line}</text>)}
        </>}
      </g>;
    })}
    <g transform="translate(980 90)"><rect width="190" height="630" className="plan-title-box" /><text x="14" y="30" className="plan-title-small">PROJECT</text>{titleLines.map((line,i)=><text key={i} x="14" y={57+i*24} className="plan-title-name">{line}</text>)}<line x1="0" y1="145" x2="190" y2="145" /><text x="14" y="175" className="plan-title-small">DRAWING</text><text x="14" y="210" className="plan-title-code">{geometry.sheet}</text><line x1="0" y1="232" x2="190" y2="232" /><text x="14" y="263" className="plan-title-small">FLOOR</text><text x="14" y="297" className="plan-title-name">Level {floor.level || "not specified"}</text><line x1="0" y1="318" x2="190" y2="318" /><text x="14" y="349" className="plan-title-small">SOURCE</text><text x="14" y="377" className="plan-title-name">Structured geometry</text><text x="14" y="408" className="plan-title-small">WALL HEIGHT</text><text x="14" y="436" className="plan-title-name">{geometry.wall_height.toLocaleString("en-GB")} mm</text><line x1="0" y1="520" x2="190" y2="520" /><text x="14" y="557" className="plan-title-small">REVISION</text><text x="14" y="595" className="plan-title-code">{geometry.revision}</text></g>
    <g transform="translate(84 752)"><rect width={barWidth/2} height="9" className="plan-scale-dark" /><rect x={barWidth/2} width={barWidth/2} height="9" className="plan-scale-light" /><text y="31" className="plan-coordinate">0</text><text x={barWidth} y="31" textAnchor="end" className="plan-coordinate">{barMm/1000} m</text></g>
    <text x="300" y="759" className="plan-footnote">Coordinates in mm · door swings schematic</text><text x="300" y="785" className="plan-footnote">Read the source PDF for construction details.</text>
  </svg>;
}

interface RoomLabel {
  room: Room;
  index: number;
  lines: string[];
  fontSize: number;
  width: number;
  height: number;
  marker: boolean;
}

function layoutRoomLabels(rooms: Room[], walls: Wall[], scale: number, zoom: number): RoomLabel[] {
  const labels: RoomLabel[] = [];
  for (const [index, room] of rooms.entries()) {
    let halfWidth = 88, halfHeight = 44;
    // Intersections with the room's horizontal and vertical axes bound text to its walls.
    for (const wall of walls) {
      const dx = wall.x2 - wall.x1, dy = wall.y2 - wall.y1;
      const wallInset = Math.max(wall.thickness * scale / 2, wall.kind === "exterior" ? 3 : 1.5) + 3;
      if (dy && room.y >= Math.min(wall.y1, wall.y2) && room.y <= Math.max(wall.y1, wall.y2)) {
        const distance = Math.abs(wall.x1 + (room.y - wall.y1) / dy * dx - room.x) * scale;
        halfWidth = Math.min(halfWidth, Math.max(0, distance - wallInset));
      }
      if (dx && room.x >= Math.min(wall.x1, wall.x2) && room.x <= Math.max(wall.x1, wall.x2)) {
        const distance = Math.abs(wall.y1 + (room.x - wall.x1) / dx * dy - room.y) * scale;
        halfHeight = Math.min(halfHeight, Math.max(0, distance - wallInset));
      }
    }
    const minimumFont = Math.max(8, 14 / zoom);
    let label: RoomLabel | undefined;
    for (let fontSize = 20; fontSize >= minimumFont && !label; fontSize -= 1) {
      const availableCharacters = Math.floor((halfWidth * 2 - 10) / (fontSize * .65));
      if (availableCharacters < 1) continue;
      const lines = wrap(room.label, availableCharacters);
      const width = Math.max(...lines.map(line => line.length)) * fontSize * .65 + 10;
      const height = lines.length * fontSize * 1.2 + 8;
      if (width <= halfWidth * 2 && height <= halfHeight * 2 && fitsRoomLabel(room, width, height, rooms, labels, scale)) {
        label = { room, index, lines, width, height, fontSize, marker: false };
      }
    }
    if (!label) {
      const nearest = Math.min(...rooms.filter(other => other !== room).map(other => Math.hypot(other.x - room.x, other.y - room.y) * scale));
      const fontSize = Math.max(8, 12 / zoom);
      const number = String(index + 1);
      const width = number.length * fontSize * .65 + 8, height = fontSize * 1.2 + 6;
      const numbered = width <= halfWidth * 2 && height <= halfHeight * 2 && fitsRoomLabel(room, width, height, rooms, labels, scale);
      const diameter = Math.max(.5, Math.min(6, nearest * .45, halfWidth * 2, halfHeight * 2));
      label = { room, index, lines: numbered ? [number] : [], width: numbered ? width : diameter, height: numbered ? height : diameter, fontSize, marker: true };
    }
    labels.push(label);
  }
  return labels;
}

function fitsRoomLabel(room: Room, width: number, height: number, rooms: Room[], labels: RoomLabel[], scale: number): boolean {
  // Reserve room centres as well as already placed labels; the result is independent of density.
  return rooms.every(other => other === room || Math.abs(other.x-room.x)*scale > width/2+4 || Math.abs(other.y-room.y)*scale > height/2+4)
    && labels.every(other => Math.abs(other.room.x-room.x)*scale > (width+other.width)/2+3 || Math.abs(other.room.y-room.y)*scale > (height+other.height)/2+3);
}

function wrap(value: string, width: number): string[] {
  const result: string[]=[];
  for (const word of value.split(/\s+/)) {
    if (result.length && result[result.length-1].length+word.length+1 <= width) result[result.length-1]+=" "+word;
    else result.push(word);
  }
  return result.length ? result : [value];
}
